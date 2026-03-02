from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import AppConfig
from src.domain.events import EventType, Task, TaskPriority, TaskStatus
from src.queue.priority_queue import PriorityTaskQueue
from src.scheduler.recovery_service import RecoveryService
from src.storage.db import Database
from src.storage.repositories.task_repo import TaskRepository
from src.workers.retry_policy import ExponentialBackoffRetryPolicy


class RecoveryServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        cfg = AppConfig.from_env()
        self.config = replace(cfg, db_url="sqlite:///data/test_recovery.db")
        db_path = Path("data/test_recovery.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()
        self.task_repo = TaskRepository(self.db)
        self.queue = PriorityTaskQueue(max_size=100, poll_interval_seconds=0.01)
        self.retry_policy = ExponentialBackoffRetryPolicy(
            max_retries=self.config.retry.max_retries,
            base_delay_seconds=self.config.retry.base_delay_seconds,
            max_delay_seconds=self.config.retry.max_delay_seconds,
        )
        self.recovery = RecoveryService(self.task_repo, self.queue, self.retry_policy)

    def _new_task(self, task_id: str) -> Task:
        return Task(
            task_id=task_id,
            event_type=EventType.DISCOVER_SESSIONS,
            entity_id="hxguquan",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.DISCOVERY,
            payload={"url": "https://www.hxguquan.com/"},
            retry_count=0,
            max_retries=3,
        )

    def test_recover_failed_task_reuses_same_task_id_and_updates_retry(self) -> None:
        # 失败任务恢复时应更新原记录，不应尝试插入新 task_id 行。
        task = self._new_task("task_failed_1")
        self.task_repo.upsert_task(task)
        self.task_repo.mark_failed(task.task_id, error="network", retry_count=1, max_retries=task.max_retries)

        requeue_count = self.recovery.recover(limit=20)
        self.assertEqual(1, requeue_count)
        self.assertEqual(1, self.queue.qsize())

        state = self.task_repo.get_by_task_id(task.task_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(TaskStatus.PENDING, state.status)
        self.assertEqual(2, state.retry_count)
        self.assertEqual("https://www.hxguquan.com/", state.payload.get("url"))

        with self.db.connection() as conn:
            row_count = conn.execute("SELECT COUNT(1) AS c FROM task_state").fetchone()["c"]
        self.assertEqual(1, row_count)

    def test_recover_running_task_resets_to_pending(self) -> None:
        # running 任务重启后应回到 pending 并重新入队。
        task = self._new_task("task_running_1")
        self.task_repo.upsert_task(task)
        self.task_repo.mark_running(task.task_id)

        requeue_count = self.recovery.recover(limit=20)
        self.assertEqual(1, requeue_count)
        self.assertEqual(1, self.queue.qsize())

        state = self.task_repo.get_by_task_id(task.task_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(TaskStatus.PENDING, state.status)
        self.assertEqual(0, state.retry_count)
        self.assertEqual("https://www.hxguquan.com/", state.payload.get("url"))

        recovered_task = self.queue.get(timeout=0.2)
        self.assertEqual("https://www.hxguquan.com/", recovered_task.payload.get("url"))
        self.queue.task_done(recovered_task.task_id)

    def test_recover_dead_task_skipped(self) -> None:
        # dead 任务不应再入队。
        task = self._new_task("task_dead_1")
        self.task_repo.upsert_task(task)
        self.task_repo.mark_failed(task.task_id, error="fatal", retry_count=task.max_retries, max_retries=task.max_retries)

        requeue_count = self.recovery.recover(limit=20)
        self.assertEqual(0, requeue_count)
        self.assertEqual(0, self.queue.qsize())


if __name__ == "__main__":
    unittest.main()
