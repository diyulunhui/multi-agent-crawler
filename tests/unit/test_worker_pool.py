from __future__ import annotations

import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from src.config.settings import AppConfig
from src.domain.events import EventType, Task, TaskPriority
from src.queue.priority_queue import PriorityTaskQueue
from src.workers.pool import WorkerPool
from src.workers.retry_policy import ExponentialBackoffRetryPolicy


class _ExecutorResult:
    def __init__(self, success: bool, message: str = "") -> None:
        self.success = success
        self.message = message


class _MemoryTaskRepo:
    def __init__(self) -> None:
        self.running: list[str] = []
        self.succeeded: list[str] = []
        self.failed: list[tuple[str, str, int]] = []
        self.retried: list[tuple[str, int]] = []
        self._lock = threading.Lock()

    def mark_running(self, task_id: str) -> None:
        with self._lock:
            self.running.append(task_id)

    def mark_succeeded(self, task_id: str) -> None:
        with self._lock:
            self.succeeded.append(task_id)

    def mark_failed(self, task_id: str, error: str, retry_count: int, max_retries: int) -> None:
        with self._lock:
            self.failed.append((task_id, error, retry_count))

    def schedule_retry(self, task_id: str, run_at_iso: str, retry_count: int) -> None:
        with self._lock:
            self.retried.append((task_id, retry_count))


class _SystemExitOnFirstGetQueue(PriorityTaskQueue):
    def __init__(self, max_size: int = 1000, poll_interval_seconds: float = 0.01) -> None:
        super().__init__(max_size=max_size, poll_interval_seconds=poll_interval_seconds)
        self._first = True
        self._lock = threading.Lock()

    def get(self, timeout: float | None = None, allowed_event_types=None):
        with self._lock:
            if self._first:
                self._first = False
                raise SystemExit("fatal get")
        return super().get(timeout=timeout, allowed_event_types=allowed_event_types)


class WorkerPoolTestCase(unittest.TestCase):
    def setUp(self) -> None:
        cfg = AppConfig.from_env()
        queue_cfg = replace(cfg.queue, worker_count=1, poll_interval_seconds=0.01)
        self.config = replace(cfg, queue=queue_cfg)
        self.retry_policy = ExponentialBackoffRetryPolicy(max_retries=1, base_delay_seconds=0, max_delay_seconds=0)

    def _task(self, entity_id: str) -> Task:
        return Task(
            event_type=EventType.DISCOVER_SESSIONS,
            entity_id=entity_id,
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.DISCOVERY,
            payload={"url": "https://www.hxguquan.com/"},
        )

    def test_base_exception_should_not_kill_worker(self) -> None:
        queue = PriorityTaskQueue(max_size=100, poll_interval_seconds=0.01)
        repo = _MemoryTaskRepo()
        first = {"raised": False}

        def dispatch(task: Task):
            if not first["raised"]:
                first["raised"] = True
                raise SystemExit("fatal dispatch")
            return _ExecutorResult(success=True)

        pool = WorkerPool(
            config=self.config,
            queue=queue,
            task_repo=repo,  # type: ignore[arg-type]
            dispatcher=dispatch,
            retry_policy=self.retry_policy,
        )
        pool.start(worker_count=1)
        queue.put(self._task("fatal"))
        queue.put(self._task("ok"))

        deadline = time.time() + 3
        while time.time() < deadline:
            if len(repo.failed) >= 1 and len(repo.succeeded) >= 2:
                break
            time.sleep(0.02)
        pool.stop(graceful=True)

        self.assertGreaterEqual(len(repo.failed), 1)
        self.assertGreaterEqual(len(repo.succeeded), 2)
        self.assertIn("SystemExit", repo.failed[0][1])

    def test_monitor_should_restart_worker_after_fatal_get(self) -> None:
        queue = _SystemExitOnFirstGetQueue(max_size=100, poll_interval_seconds=0.01)
        repo = _MemoryTaskRepo()

        def dispatch(task: Task):
            return _ExecutorResult(success=True)

        pool = WorkerPool(
            config=self.config,
            queue=queue,
            task_repo=repo,  # type: ignore[arg-type]
            dispatcher=dispatch,
            retry_policy=self.retry_policy,
        )
        pool.start(worker_count=1)
        task = self._task("recover")
        queue.put(task)

        deadline = time.time() + 3
        while time.time() < deadline:
            if task.task_id in repo.succeeded:
                break
            time.sleep(0.02)
        pool.stop(graceful=True)

        self.assertIn(task.task_id, repo.succeeded)


if __name__ == "__main__":
    unittest.main()
