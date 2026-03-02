from __future__ import annotations

import time
from datetime import datetime, timezone
from queue import Empty, PriorityQueue
from threading import Lock

from src.domain.events import Task
from src.queue.task_item import TaskQueueItem


class PriorityTaskQueue:
    def __init__(self, max_size: int = 10000, poll_interval_seconds: float = 0.5) -> None:
        # 使用标准库 PriorityQueue，避免引入外部中间件。
        self._queue: PriorityQueue = PriorityQueue(maxsize=max_size)
        self._poll_interval_seconds = poll_interval_seconds
        self._inflight: set[str] = set()
        self._lock = Lock()

    def put(self, task: Task) -> None:
        # 任务按 (priority, run_at_ts) 自动排序。
        item = TaskQueueItem.from_task(task)
        self._queue.put(item.prioritized)

    def get(self, timeout: float | None = None, allowed_event_types=None) -> Task:
        # 取出下一个已到期任务；未到期任务会回队并短暂休眠。
        deadline = None if timeout is None else datetime.now(timezone.utc).timestamp() + timeout

        while True:
            remaining = None
            if deadline is not None:
                remaining = max(deadline - datetime.now(timezone.utc).timestamp(), 0.0)
                if remaining <= 0:
                    raise Empty("PriorityTaskQueue get timeout")

            prioritized = self._queue.get(timeout=remaining)
            item = TaskQueueItem(prioritized=prioritized)

            now = datetime.now(timezone.utc)
            if item.run_at <= now:
                with self._lock:
                    self._inflight.add(item.task.task_id)
                return item.task

            wait_seconds = (item.run_at - now).total_seconds()
            self._queue.put(prioritized)
            self._queue.task_done()
            sleep_for = min(wait_seconds, self._poll_interval_seconds)

            if deadline is not None:
                sleep_for = min(sleep_for, max(deadline - datetime.now(timezone.utc).timestamp(), 0.0))
                if sleep_for <= 0:
                    raise Empty("PriorityTaskQueue get timeout")

            # 避免忙轮询：短暂睡眠后再检查到期任务。
            time.sleep(sleep_for)

    def task_done(self, task_id: str) -> None:
        # worker 执行完成后确认，释放队列 unfinished 计数。
        with self._lock:
            if task_id in self._inflight:
                self._inflight.remove(task_id)
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()

    def join(self) -> None:
        self._queue.join()
