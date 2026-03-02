from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import AppConfig
from src.domain.events import EventType, SessionType, SnapshotType, Task, TaskPriority
from src.domain.models import AuctionSession
from src.scraping.parsers.hx_parser import ParsedLot
from src.services.result_service import ResultService
from src.services.snapshot_service import SnapshotService
from src.storage.db import Database
from src.storage.object_store import LocalObjectStore
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.session_repo import SessionRepository
from src.workers.executors.snapshot_executor import SnapshotExecutor
from src.workers.monitor.extension_monitor import ExtensionMonitor


class _FakeAdapter:
    def fetch_page(self, url, context=None):
        class Raw:
            pass

        raw = Raw()
        raw.url = url
        raw.text = "<html>integration</html>"
        return raw

    def parse_lots(self, raw):
        return [
            ParsedLot(
                lot_id="l_int",
                session_id="s_int",
                title_raw="lot",
                description_raw="desc",
                end_time="2026-03-01T10:00:00",
                status="closed",
                current_price="200",
                bid_count=3,
                category="coin",
                grade_agency="PCGS",
                grade_score="MS64",
            )
        ]


class SnapshotPipelineIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        # 使用独立数据库和存储目录。
        cfg = AppConfig.from_env()
        self.config = replace(
            cfg,
            db_url="sqlite:///data/test_integration.db",
            storage_root=Path("data/test_integration_raw"),
        )

        db_path = Path("data/test_integration.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()

        now = datetime.now(timezone.utc)
        SessionRepository(self.db).upsert_session(
            AuctionSession("s_int", SessionType.SPECIAL, "session", now, "http://session", now, now)
        )
        LotRepository(self.db).upsert_lot(LotRepository(self.db).new("l_int", "s_int", "lot", now))

    def test_snapshot_and_result_written(self) -> None:
        adapter = _FakeAdapter()
        monitor = ExtensionMonitor(adapter, poll_seconds=0, max_minutes=1, sleep_fn=lambda _: None)
        snapshot_service = SnapshotService(self.config, self.db, LocalObjectStore(self.config.storage_root))
        result_service = ResultService(self.db)
        executor = SnapshotExecutor(self.config, adapter, monitor, snapshot_service, result_service)

        task = Task(
            event_type=EventType.SNAPSHOT_FINAL_MONITOR,
            entity_id="l_int",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.FINAL_MONITOR,
            payload={"url": "http://session", "lot_id": "l_int", "session_id": "s_int"},
        )
        result = executor.execute(task)
        self.assertTrue(result.success)

        with self.db.connection() as conn:
            snap_count = conn.execute("SELECT COUNT(1) AS c FROM lot_snapshot WHERE lot_id='l_int'").fetchone()["c"]
            res_count = conn.execute("SELECT COUNT(1) AS c FROM lot_result WHERE lot_id='l_int'").fetchone()["c"]

        self.assertGreaterEqual(snap_count, 1)
        self.assertEqual(1, res_count)


if __name__ == "__main__":
    unittest.main()
