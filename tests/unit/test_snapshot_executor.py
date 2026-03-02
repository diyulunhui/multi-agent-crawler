from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from src.config.settings import AppConfig
from src.domain.events import EventType, Task, TaskPriority
from src.domain.events import SnapshotType
from src.scraping.parsers.hx_parser import ParsedLot, ParsedLotDetail
from src.workers.executors.snapshot_executor import SnapshotExecutor
from src.workers.monitor.extension_monitor import MonitorOutcome


class _FakeSnapshotService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def save_from_parsed(
        self,
        lot_id: str,
        snapshot_type: SnapshotType,
        current_price,
        bid_count,
        raw_html: str,
        snapshot_time: datetime,
        session_id: str,
        quality_score: Decimal = Decimal("1.0"),
    ) -> None:
        self.calls.append(
            {
                "lot_id": lot_id,
                "snapshot_type": snapshot_type,
                "current_price": current_price,
                "bid_count": bid_count,
                "raw_html": raw_html,
                "snapshot_time": snapshot_time,
                "session_id": session_id,
                "quality_score": quality_score,
            }
        )


class _FakeResultService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert_from_snapshot(
        self,
        lot_id: str,
        final_price,
        final_end_time: datetime | None,
        confidence_score,
        decided_from_snapshot: str,
        is_unsold: bool = False,
        is_withdrawn: bool = False,
    ) -> None:
        self.calls.append(
            {
                "lot_id": lot_id,
                "final_price": final_price,
                "final_end_time": final_end_time,
                "confidence_score": confidence_score,
                "decided_from_snapshot": decided_from_snapshot,
                "is_unsold": is_unsold,
                "is_withdrawn": is_withdrawn,
            }
        )


class _FakeAdapter:
    def __init__(self, detail: ParsedLotDetail | None = None) -> None:
        self.detail = detail

    def fetch_page(self, url, context=None):
        class Raw:
            pass

        raw = Raw()
        raw.url = url
        raw.text = "<html>snapshot</html>"
        return raw

    def parse_lots(self, raw):
        # 默认返回空，触发“列表里找不到 lot”的补偿逻辑。
        return []

    def fetch_lot_detail(self, lot_id: str):
        return self.detail


class _FakeMonitor:
    def __init__(self, outcome: MonitorOutcome) -> None:
        self.outcome = outcome

    def monitor(self, url: str, lot_id: str, session_id: str) -> MonitorOutcome:
        return self.outcome


class _OpenLotAdapter(_FakeAdapter):
    def parse_lots(self, raw):
        return [
            ParsedLot(
                lot_id="lot_open",
                session_id="s_open",
                title_raw="open lot",
                description_raw=None,
                end_time="2026-02-28T20:00:00+08:00",
                status="running",
                current_price="120",
                bid_count=3,
                category=None,
                grade_agency=None,
                grade_score=None,
            )
        ]


class SnapshotExecutorFallbackTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.config = replace(AppConfig.from_env())

    def test_pre_snapshot_missing_lot_writes_placeholder_and_no_retry_failure(self) -> None:
        # PRE 快照找不到 lot 时应写占位快照并返回 success，避免反复无效重试。
        snapshot_service = _FakeSnapshotService()
        result_service = _FakeResultService()
        executor = SnapshotExecutor(
            self.config,
            _FakeAdapter(detail=None),
            _FakeMonitor(MonitorOutcome(lot=None, closed=False, timed_out=True, polls=1)),
            snapshot_service,
            result_service,
        )

        task = Task(
            event_type=EventType.SNAPSHOT_PRE5,
            entity_id="lot_1",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.PRE5,
            payload={"url": "https://www.hxguquan.com/goods-list.html?gid=1", "lot_id": "lot_1", "session_id": "s_1"},
        )
        result = executor.execute(task)

        self.assertTrue(result.success)
        self.assertEqual(1, len(snapshot_service.calls))
        self.assertEqual(SnapshotType.PRE5, snapshot_service.calls[0]["snapshot_type"])
        self.assertEqual(SnapshotExecutor.MISSING_SNAPSHOT_QUALITY, snapshot_service.calls[0]["quality_score"])
        self.assertEqual(0, len(result_service.calls))

    def test_final_missing_lot_uses_detail_fallback_and_marks_withdrawn(self) -> None:
        # FINAL 监控没找到 lot，但详情接口给出“已撤拍”时应回退写终态并标记撤拍。
        detail = ParsedLotDetail(
            lot_id="lot_2",
            title_raw="lot_2",
            description_raw=None,
            end_time=None,
            status="closed",
            current_price=None,
            start_price=None,
            bid_count=None,
            look_count=None,
            fee_rate=None,
            winner=None,
            bid_history_html=None,
            image_primary=None,
            images_json=None,
            video_url=None,
            labels_json=None,
            raw_json='{"status":"已撤拍"}',
        )
        snapshot_service = _FakeSnapshotService()
        result_service = _FakeResultService()
        executor = SnapshotExecutor(
            self.config,
            _FakeAdapter(detail=detail),
            _FakeMonitor(MonitorOutcome(lot=None, closed=False, timed_out=True, polls=3)),
            snapshot_service,
            result_service,
        )

        task = Task(
            event_type=EventType.SNAPSHOT_FINAL_MONITOR,
            entity_id="lot_2",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.FINAL_MONITOR,
            payload={"url": "https://www.hxguquan.com/goods-list.html?gid=2", "lot_id": "lot_2", "session_id": "s_2"},
        )
        result = executor.execute(task)

        self.assertTrue(result.success)
        self.assertEqual(1, len(snapshot_service.calls))
        self.assertEqual(SnapshotType.FINAL, snapshot_service.calls[0]["snapshot_type"])
        self.assertEqual(SnapshotExecutor.DETAIL_FALLBACK_QUALITY, snapshot_service.calls[0]["quality_score"])
        self.assertEqual(1, len(result_service.calls))
        self.assertTrue(result_service.calls[0]["is_withdrawn"])
        self.assertFalse(result_service.calls[0]["is_unsold"])
        self.assertIsNotNone(result_service.calls[0]["final_end_time"])

    def test_final_nonblocking_monitor_reschedules_open_lot(self) -> None:
        # 注入重排回调后，FINAL 未闭合应快速返回并延后再入队，不阻塞 worker。
        snapshot_service = _FakeSnapshotService()
        result_service = _FakeResultService()
        followups: list[tuple[str, datetime, dict[str, object]]] = []

        def _reschedule(task: Task, run_at: datetime, payload_updates: dict[str, object]) -> None:
            followups.append((task.entity_id, run_at, payload_updates))

        executor = SnapshotExecutor(
            self.config,
            _OpenLotAdapter(detail=None),
            _FakeMonitor(MonitorOutcome(lot=None, closed=False, timed_out=True, polls=1)),
            snapshot_service,
            result_service,
            reschedule_final_monitor=_reschedule,
        )

        task = Task(
            event_type=EventType.SNAPSHOT_FINAL_MONITOR,
            entity_id="lot_open",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.FINAL_MONITOR,
            payload={"url": "https://www.hxguquan.com/goods-list.html?gid=3", "lot_id": "lot_open", "session_id": "s_open"},
        )
        result = executor.execute(task)

        self.assertTrue(result.success)
        self.assertEqual(1, len(snapshot_service.calls))
        self.assertEqual(1, len(result_service.calls))
        self.assertEqual(1, len(followups))
        self.assertEqual("lot_open", followups[0][0])
        self.assertIn("monitor_deadline_at", followups[0][2])
        self.assertEqual(1, followups[0][2]["monitor_round"])
        self.assertIsNone(result_service.calls[0]["final_end_time"])


if __name__ == "__main__":
    unittest.main()
