from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.classification.lot_classifier_agent import LotClassifierAgent
from src.config.settings import AppConfig
from src.domain.events import EventType, SessionType, Task, TaskPriority
from src.domain.models import AuctionSession
from src.scraping.parsers.hx_parser import ParsedLot, ParsedLotDetail
from src.storage.db import Database
from src.storage.repositories.lot_classification_repo import LotClassificationRepository
from src.storage.repositories.lot_detail_repo import LotDetailRepository
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.lot_structured_repo import LotStructuredRepository
from src.storage.repositories.review_queue_repo import ReviewQueueRepository
from src.storage.repositories.session_repo import SessionRepository
from src.structuring.title_description_structured_agent import TitleDescriptionStructuredAgent
from src.workers.executors.lot_executor import LotDiscoveryExecutor


class _FakeAdapter:
    def fetch_page(self, url, context=None):
        # 发现流程仅依赖 raw.url/raw.text，这里返回最小桩对象。
        class Raw:
            pass

        raw = Raw()
        raw.url = url
        raw.text = "<html>lots</html>"
        return raw

    def parse_lots(self, raw):
        # 返回一个信息不足的 lot，用于触发结构化低置信度分支。
        return [
            ParsedLot(
                lot_id="l_low",
                session_id="s_low",
                title_raw="测试样本",
                description_raw="",
                end_time=datetime.now(timezone.utc).isoformat(),
                status="bidding",
                current_price=None,
                bid_count=None,
                category=None,
                grade_agency=None,
                grade_score=None,
            )
        ]

    def fetch_lot_detail(self, lot_id: str):
        # 详情同样不给核心字段，确保进入 review_queue。
        return ParsedLotDetail(
            lot_id=lot_id,
            title_raw="测试样本",
            description_raw="品相如图",
            end_time=datetime.now(timezone.utc).isoformat(),
            status="bidding",
            current_price="100",
            start_price="50",
            bid_count=1,
            look_count=2,
            fee_rate="4.5",
            winner=None,
            bid_history_html=None,
            image_primary=None,
            images_json=None,
            video_url=None,
            labels_json=None,
            raw_json='{"itemcode":"l_low"}',
        )


class _FakeScheduler:
    def schedule_lot_snapshots_with_payload(self, lot, now=None, extra_payload=None):
        # 该用例只验证结构化链路，不关心快照任务数量。
        return []

    def schedule_lot_structuring(self, lot_id: str, now=None):
        # DISCOVER_LOTS 阶段仅验证会派发结构化任务，不在此处执行。
        return []


class LotExecutorStructuredTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 搭建独立测试数据库。
        cfg = AppConfig.from_env()
        self.config = replace(cfg, db_url="sqlite:///data/test_lot_executor_structured.db")

        db_path = Path("data/test_lot_executor_structured.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()

        now = datetime.now(timezone.utc)
        SessionRepository(self.db).upsert_session(
            AuctionSession(
                session_id="s_low",
                session_type=SessionType.NORMAL,
                title="普通拍卖",
                scheduled_end_time=now,
                source_url="https://www.hxguquan.com/goods-list.html?gid=9001",
                discovered_at=now,
                updated_at=now,
            )
        )

    def test_execute_writes_structured_and_review_queue(self) -> None:
        # 结构化已异步化：DISCOVER_LOTS 只负责发现与派发；STRUCTURE_LOT 负责清洗入库。
        executor = LotDiscoveryExecutor(
            self.config,
            _FakeAdapter(),
            LotRepository(self.db),
            LotDetailRepository(self.db),
            LotClassificationRepository(self.db),
            LotClassifierAgent(),
            LotStructuredRepository(self.db),
            ReviewQueueRepository(self.db),
            TitleDescriptionStructuredAgent(),
            _FakeScheduler(),
        )
        task = Task(
            event_type=EventType.DISCOVER_LOTS,
            entity_id="s_low",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.DISCOVERY,
            payload={"url": "https://www.hxguquan.com/goods-list.html?gid=9001", "session_id": "s_low"},
        )
        result = executor.execute(task)
        self.assertTrue(result.success)
        self.assertEqual(1, result.processed_count)
        self.assertEqual(0, result.emitted_task_count)

        with self.db.connection() as conn:
            structured_count = conn.execute("SELECT COUNT(1) AS c FROM lot_structured").fetchone()["c"]
            review_count = conn.execute("SELECT COUNT(1) AS c FROM review_queue WHERE status='pending'").fetchone()["c"]
        self.assertEqual(0, structured_count)
        self.assertEqual(0, review_count)

        structure_task = Task(
            event_type=EventType.STRUCTURE_LOT,
            entity_id="l_low",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.NEXTDAY_BACKFILL,
            payload={"lot_id": "l_low"},
        )
        structure_result = executor.execute(structure_task)
        self.assertTrue(structure_result.success)

        with self.db.connection() as conn:
            structured_count_after = conn.execute("SELECT COUNT(1) AS c FROM lot_structured").fetchone()["c"]
            review_count_after = conn.execute("SELECT COUNT(1) AS c FROM review_queue WHERE status='pending'").fetchone()["c"]
        self.assertEqual(1, structured_count_after)
        self.assertEqual(1, review_count_after)


if __name__ == "__main__":
    unittest.main()
