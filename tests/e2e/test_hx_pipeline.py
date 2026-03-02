from __future__ import annotations

import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import AppConfig
from src.domain.events import EventType
from src.classification.lot_classifier_agent import LotClassifierAgent
from src.queue.priority_queue import PriorityTaskQueue
from src.scheduler.task_scheduler import TaskScheduler
from src.scraping.parsers.hx_parser import ParsedLot, ParsedLotDetail, ParsedSession
from src.services.result_service import ResultService
from src.services.snapshot_service import SnapshotService
from src.storage.db import Database
from src.storage.object_store import LocalObjectStore
from src.storage.repositories.lot_classification_repo import LotClassificationRepository
from src.storage.repositories.lot_detail_repo import LotDetailRepository
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.lot_structured_repo import LotStructuredRepository
from src.storage.repositories.review_queue_repo import ReviewQueueRepository
from src.storage.repositories.session_repo import SessionRepository
from src.storage.repositories.task_repo import TaskRepository
from src.structuring.title_description_structured_agent import TitleDescriptionStructuredAgent
from src.workers.executors.discovery_executor import DiscoveryExecutor
from src.workers.executors.lot_executor import LotDiscoveryExecutor
from src.workers.executors.snapshot_executor import SnapshotExecutor
from src.workers.monitor.extension_monitor import ExtensionMonitor
from src.workers.pool import WorkerPool
from src.workers.retry_policy import ExponentialBackoffRetryPolicy


class _FakeAdapter:
    def fetch_page(self, url, context=None):
        class Raw:
            pass

        raw = Raw()
        raw.url = url
        raw.text = "<html>e2e</html>"
        return raw

    def parse_session(self, raw):
        return [
            ParsedSession(
                session_id="s_e2e",
                session_type="SPECIAL",
                title="session",
                source_url="https://www.hxguquan.com/goods-list.html?gid=74587",
                scheduled_end_time="2026-03-01T10:00:00",
            )
        ]

    def parse_lots(self, raw):
        # 使用当前时间，确保 PRE5 任务立即到期可执行。
        now_iso = datetime.now(timezone.utc).isoformat()
        return [
            ParsedLot(
                lot_id="l_e2e",
                session_id="s_e2e",
                title_raw="PCGS MS64 袁大头 三年 壹圆",
                description_raw="原味包浆",
                end_time=now_iso,
                status="closed",
                current_price="300",
                bid_count=5,
                category="coin",
                grade_agency="PCGS",
                grade_score="MS65",
            )
        ]

    def fetch_lot_detail(self, lot_id):
        # E2E 场景返回固定详情，覆盖详情入库链路。
        return ParsedLotDetail(
            lot_id=lot_id,
            title_raw="PCGS MS64 袁大头 三年 壹圆",
            description_raw="原味包浆",
            end_time=datetime.now(timezone.utc).isoformat(),
            status="closed",
            current_price="300",
            start_price="100",
            bid_count=5,
            look_count=10,
            fee_rate="4.5",
            winner="tester",
            bid_history_html="<ul><li>bid</li></ul>",
            image_primary="https://imgali.huaxiaguquan.com/pic/a.jpg",
            images_json='["https://imgali.huaxiaguquan.com/pic/a.jpg"]',
            video_url="https://imgali.huaxiaguquan.com/video/a.mp4",
            labels_json='["机制币"]',
            raw_json='{"itemcode":"l_e2e"}',
        )


class HxPipelineE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        # 准备独立的 E2E 环境。
        cfg = AppConfig.from_env()
        self.config = replace(
            cfg,
            db_url="sqlite:///data/test_e2e.db",
            storage_root=Path("data/test_e2e_raw"),
            queue=replace(cfg.queue, worker_count=1, poll_interval_seconds=0.05),
            schedule=replace(cfg.schedule, enable_pre1=False, enable_final_monitor=True),
        )

        db_path = Path("data/test_e2e.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()

    def test_end_to_end_pipeline(self) -> None:
        # 组装执行链路。
        queue = PriorityTaskQueue(max_size=2000, poll_interval_seconds=0.02)
        task_repo = TaskRepository(self.db)
        scheduler = TaskScheduler(self.config, task_repo, queue)

        adapter = _FakeAdapter()
        monitor = ExtensionMonitor(adapter, poll_seconds=0, max_minutes=1, sleep_fn=lambda _: None)
        snapshot_service = SnapshotService(self.config, self.db, LocalObjectStore(self.config.storage_root))
        result_service = ResultService(self.db)

        discovery_executor = DiscoveryExecutor(self.config, adapter, SessionRepository(self.db), scheduler)
        lot_executor = LotDiscoveryExecutor(
            self.config,
            adapter,
            LotRepository(self.db),
            LotDetailRepository(self.db),
            LotClassificationRepository(self.db),
            LotClassifierAgent(),
            LotStructuredRepository(self.db),
            ReviewQueueRepository(self.db),
            TitleDescriptionStructuredAgent(),
            scheduler,
        )
        snapshot_executor = SnapshotExecutor(self.config, adapter, monitor, snapshot_service, result_service)

        def dispatch(task):
            if task.event_type == EventType.DISCOVER_SESSIONS:
                return discovery_executor.execute(task)
            if task.event_type in {EventType.DISCOVER_LOTS, EventType.STRUCTURE_LOT}:
                return lot_executor.execute(task)
            return snapshot_executor.execute(task)

        pool = WorkerPool(
            config=self.config,
            queue=queue,
            task_repo=task_repo,
            dispatcher=dispatch,
            retry_policy=ExponentialBackoffRetryPolicy(
                self.config.retry.max_retries,
                self.config.retry.base_delay_seconds,
                self.config.retry.max_delay_seconds,
            ),
        )
        pool.start(worker_count=1)

        # 投递发现任务，驱动全链路执行。
        scheduler.schedule_discovery(now=datetime.now(timezone.utc), entry_url="http://entry/e2e")

        # 等待任务流转完成。
        deadline = time.time() + 5
        while time.time() < deadline:
            unfinished = task_repo.get_unfinished_tasks(limit=20)
            if not unfinished and queue.qsize() == 0:
                break
            time.sleep(0.05)

        pool.stop(graceful=True)

        with self.db.connection() as conn:
            session_count = conn.execute("SELECT COUNT(1) AS c FROM auction_session").fetchone()["c"]
            lot_count = conn.execute("SELECT COUNT(1) AS c FROM lot").fetchone()["c"]
            detail_count = conn.execute("SELECT COUNT(1) AS c FROM lot_detail").fetchone()["c"]
            classification_count = conn.execute("SELECT COUNT(1) AS c FROM lot_classification").fetchone()["c"]
            structured_count = conn.execute("SELECT COUNT(1) AS c FROM lot_structured").fetchone()["c"]
            snapshot_count = conn.execute("SELECT COUNT(1) AS c FROM lot_snapshot").fetchone()["c"]
            result_count = conn.execute("SELECT COUNT(1) AS c FROM lot_result").fetchone()["c"]
            review_count = conn.execute("SELECT COUNT(1) AS c FROM review_queue").fetchone()["c"]

        self.assertEqual(1, session_count)
        self.assertEqual(1, lot_count)
        self.assertEqual(1, detail_count)
        self.assertEqual(1, classification_count)
        self.assertEqual(1, structured_count)
        self.assertGreaterEqual(snapshot_count, 1)
        self.assertEqual(1, result_count)
        self.assertEqual(0, review_count)


if __name__ == "__main__":
    unittest.main()
