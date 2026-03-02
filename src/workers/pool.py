from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from queue import Empty
from typing import Callable

from src.config.settings import AppConfig
from src.domain.events import EventType, Task
from src.queue.priority_queue import PriorityTaskQueue
from src.storage.repositories.task_repo import TaskRepository
from src.workers.retry_policy import ExponentialBackoffRetryPolicy


class WorkerPool:
    def __init__(
        self,
        config: AppConfig,
        queue: PriorityTaskQueue,
        task_repo: TaskRepository,
        dispatcher: Callable[[Task], object],
        retry_policy: ExponentialBackoffRetryPolicy,
        allowed_event_types: set[EventType] | None = None,
        worker_name_prefix: str = "worker",
    ) -> None:
        # 线程化 worker 池，消费优先队列并执行任务。
        self.config = config
        self.queue = queue
        self.task_repo = task_repo
        self.dispatcher = dispatcher
        self.retry_policy = retry_policy
        self.allowed_event_types = allowed_event_types
        self.worker_name_prefix = worker_name_prefix
        self._stop_event = threading.Event()
        self._threads: dict[int, threading.Thread] = {}
        self._threads_lock = threading.Lock()
        self._desired_worker_count = 0
        self._monitor_thread: threading.Thread | None = None

    def start(self, worker_count: int | None = None) -> None:
        count = max(worker_count or self.config.queue.worker_count, 1)
        self._stop_event.clear()
        self._desired_worker_count = count

        with self._threads_lock:
            for i in range(count):
                self._spawn_worker(i)
            if self._monitor_thread is None or not self._monitor_thread.is_alive():
                self._monitor_thread = threading.Thread(
                    target=self._monitor_loop,
                    name=f"{self.worker_name_prefix}-monitor",
                    daemon=True,
                )
                self._monitor_thread.start()

    def stop(self, graceful: bool = True, timeout_seconds: float = 5.0) -> None:
        # 支持优雅停机（等待线程退出）。
        self._stop_event.set()
        if graceful:
            with self._threads_lock:
                threads = list(self._threads.values())
                monitor = self._monitor_thread
            for t in threads:
                t.join(timeout=timeout_seconds)
            if monitor is not None:
                monitor.join(timeout=timeout_seconds)
        with self._threads_lock:
            self._threads.clear()
            self._monitor_thread = None
            self._desired_worker_count = 0

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                task = self.queue.get(
                    timeout=self.config.queue.poll_interval_seconds,
                    allowed_event_types=self.allowed_event_types,
                )
            except Empty:
                continue
            except Exception:
                # 队列临时异常时短暂让出 CPU，避免线程直接退出。
                time.sleep(max(self.config.queue.poll_interval_seconds, 0.05))
                continue

            try:
                dedupe_key = task.dedupe_key()
                self.task_repo.mark_running(task.task_id, dedupe_key=dedupe_key)
                result = self.dispatcher(task)
                success = bool(getattr(result, "success", False))
                if not success:
                    raise RuntimeError(getattr(result, "message", "任务执行失败"))
                self.task_repo.mark_succeeded(task.task_id, dedupe_key=dedupe_key)
            except BaseException as exc:
                self._handle_failure(task, exc)
            finally:
                self.queue.task_done(task.task_id)

    def _monitor_loop(self) -> None:
        interval = max(self.config.queue.poll_interval_seconds, 0.5)
        while not self._stop_event.is_set():
            time.sleep(interval)
            if self._stop_event.is_set():
                break
            self._ensure_workers_alive()

    def _ensure_workers_alive(self) -> None:
        with self._threads_lock:
            for slot in range(self._desired_worker_count):
                thread = self._threads.get(slot)
                if thread is not None and thread.is_alive():
                    continue
                self._spawn_worker(slot)

    def _spawn_worker(self, slot: int) -> None:
        thread = threading.Thread(
            target=self._worker_loop,
            name=f"{self.worker_name_prefix}-{slot}",
            daemon=True,
        )
        thread.start()
        self._threads[slot] = thread

    def _handle_failure(self, task: Task, error: BaseException) -> None:
        # 失败后按指数退避决定是否重试。
        decision = self.retry_policy.decide(task.retry_count)
        self.task_repo.mark_failed(
            task_id=task.task_id,
            error=f"{type(error).__name__}: {error}",
            retry_count=decision.next_retry_count,
            max_retries=task.max_retries,
            dedupe_key=task.dedupe_key(),
        )

        if not decision.should_retry:
            return

        retry_task = replace(
            task,
            run_at=datetime.now(timezone.utc) + timedelta(seconds=decision.delay_seconds),
            retry_count=decision.next_retry_count,
        )
        self.task_repo.schedule_retry(
            task_id=retry_task.task_id,
            run_at_iso=retry_task.run_at.isoformat(),
            retry_count=retry_task.retry_count,
        )
        self.queue.put(retry_task)
