from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.settings import AppConfig, ScheduleConfig
from src.domain.events import EventType, SessionType, Task, TaskPriority
from src.domain.models import AuctionSession, Lot
from src.scheduler.task_scheduler import TaskScheduler
from src.storage.db import Database
from src.storage.repositories.task_repo import TaskRepository


class TaskSchedulerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 使用独立测试库，避免污染运行环境。
        cfg = AppConfig.from_env()
        self.config = replace(
            cfg,
            db_url="sqlite:///data/test_scheduler.db",
            schedule=replace(cfg.schedule, enable_pre1=True, enable_final_monitor=True),
        )
        db_path = Path("data/test_scheduler.db")
        if db_path.exists():
            db_path.unlink()
        self.db = Database(self.config)
        self.db.init_schema()
        self.repo = TaskRepository(self.db)
        self.scheduler = TaskScheduler(self.config, self.repo, queue=None)

    def test_schedule_lot_snapshots_contains_pre5_pre1_final(self) -> None:
        # 启用 PRE1 后，应生成 PRE5/PRE1/FINAL 三类任务。
        now = datetime.now(timezone.utc)
        lot = Lot(
            lot_id="l1",
            session_id="s1",
            title_raw="lot",
            description_raw=None,
            category=None,
            grade_agency=None,
            grade_score=None,
            end_time=now + timedelta(minutes=10),
            status="bidding",
            last_seen_at=now,
            updated_at=now,
        )
        tasks = self.scheduler.schedule_lot_snapshots(lot, now=now)
        self.assertEqual(3, len(tasks))
        self.assertEqual({"SNAPSHOT_PRE5", "SNAPSHOT_PRE1", "SNAPSHOT_FINAL_MONITOR"}, {t.event_type.value for t in tasks})

    def test_schedule_closed_lot_should_skip_pre_snapshots(self) -> None:
        # 已关闭拍品不应继续调度 PRE5/PRE1，只保留 FINAL 监控任务。
        now = datetime.now(timezone.utc)
        lot = Lot(
            lot_id="l_closed",
            session_id="s1",
            title_raw="lot",
            description_raw=None,
            category=None,
            grade_agency=None,
            grade_score=None,
            end_time=now - timedelta(minutes=10),
            status="closed",
            last_seen_at=now,
            updated_at=now,
        )
        tasks = self.scheduler.schedule_lot_snapshots(lot, now=now)
        self.assertEqual(1, len(tasks))
        self.assertEqual({"SNAPSHOT_FINAL_MONITOR"}, {t.event_type.value for t in tasks})

    def test_schedule_session_scrapes_contains_stages(self) -> None:
        # 专场任务应包含结标后与次日补抓阶段。
        now = datetime.now(timezone.utc)
        session = AuctionSession(
            session_id="s2",
            session_type=SessionType.SPECIAL,
            title="special",
            scheduled_end_time=now,
            source_url="http://example/session",
            discovered_at=now,
            updated_at=now,
        )
        tasks = self.scheduler.schedule_session_scrapes(session, now=now)
        payload_stages = {t.payload.get("stage") for t in tasks}
        self.assertIn("POST_CLOSE", payload_stages)
        self.assertIn("NEXTDAY_FIX", payload_stages)

    def test_recover_unfinished_tasks_preserves_payload(self) -> None:
        # 恢复任务时应带回 task_state 持久化 payload，避免执行器缺参失败。
        now = datetime.now(timezone.utc)
        task = Task(
            event_type=EventType.SNAPSHOT_PRE5,
            entity_id="l1",
            run_at=now,
            priority=TaskPriority.PRE5,
            payload={"url": "https://www.hxguquan.com/goods-list.html?gid=1", "lot_id": "l1", "session_id": "s1"},
        )
        self.repo.upsert_task(task)
        recovered = self.scheduler.recover_unfinished_tasks(limit=5000)
        matched = [item for item in recovered if item.task_id == task.task_id]
        self.assertEqual(1, len(matched))
        self.assertEqual("https://www.hxguquan.com/goods-list.html?gid=1", matched[0].payload.get("url"))
        self.assertEqual("l1", matched[0].payload.get("lot_id"))
        self.assertEqual("s1", matched[0].payload.get("session_id"))

    def test_discover_lots_should_dedupe_by_event_and_entity(self) -> None:
        # 同一 session 重复派发 DISCOVER_LOTS 时，应复用 dedupe_key 避免队列膨胀。
        now = datetime.now(timezone.utc)
        self.scheduler.schedule_discover_lots(session_id="s_dup", source_url="https://www.hxguquan.com/goods-list.html?gid=1", now=now)
        self.scheduler.schedule_discover_lots(
            session_id="s_dup",
            source_url="https://www.hxguquan.com/goods-list.html?gid=1",
            now=now + timedelta(seconds=30),
        )
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(1) AS c FROM task_state WHERE event_type = 'DISCOVER_LOTS' AND entity_id = 's_dup'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(1, row["c"])

    def test_session_final_scrape_should_keep_multi_stage_tasks(self) -> None:
        # 专场补抓不同 stage 必须保留多条任务，不能被 dedupe 合并。
        now = datetime.now(timezone.utc)
        session = AuctionSession(
            session_id="s_stage",
            session_type=SessionType.SPECIAL,
            title="special",
            scheduled_end_time=now,
            source_url="https://www.hxguquan.com/goods-list.html?gid=2",
            discovered_at=now,
            updated_at=now,
        )
        tasks = self.scheduler.schedule_session_scrapes(session, now=now)
        self.assertGreaterEqual(len(tasks), 2)
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT COUNT(1) AS c FROM task_state WHERE event_type = 'SESSION_FINAL_SCRAPE' AND entity_id = 's_stage'"
            ).fetchone()
        self.assertIsNotNone(rows)
        self.assertGreaterEqual(rows["c"], 2)


if __name__ == "__main__":
    unittest.main()
