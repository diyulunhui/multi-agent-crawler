from __future__ import annotations

import time
from queue import Empty
from threading import Lock

from src.domain.events import EventType, Task
from src.queue.priority_queue import PriorityTaskQueue


class MultiTaskQueue:
    # 子队列扫描顺序：先保证时效链路，再执行发现与补抓。
    DEFAULT_SCAN_ORDER = [
        EventType.DISCOVER_SESSIONS,
        EventType.DISCOVER_LOTS,
        EventType.SNAPSHOT_FINAL_MONITOR,
        EventType.SNAPSHOT_PRE5,
        EventType.SNAPSHOT_PRE1,
        EventType.SESSION_FINAL_SCRAPE,
        # 结构化为异步后处理任务，避免阻塞抓取主链路。
        EventType.STRUCTURE_LOT,
    ]
    SUBQUEUE_PROBE_TIMEOUT_SECONDS = 0.001

    def __init__(self, max_size: int = 10000, poll_interval_seconds: float = 0.5) -> None:
        # 按事件类型拆分独立子队列，避免“未来高优任务”卡住全局消费。
        self._poll_interval_seconds = poll_interval_seconds
        self._sub_queues = {
            event_type: PriorityTaskQueue(max_size=max_size, poll_interval_seconds=poll_interval_seconds)
            for event_type in EventType
        }
        self._scan_order = list(self.DEFAULT_SCAN_ORDER)
        for event_type in EventType:
            if event_type not in self._scan_order:
                self._scan_order.append(event_type)
        self._next_scan_index_by_scope: dict[str, int] = {}
        self._inflight_task_to_event: dict[str, EventType] = {}
        self._lock = Lock()

    def put(self, task: Task) -> None:
        queue = self._sub_queues.get(task.event_type)
        if queue is None:
            queue = self._sub_queues[EventType.DISCOVER_SESSIONS]
        queue.put(task)

    def get(
        self,
        timeout: float | None = None,
        allowed_event_types: set[EventType] | None = None,
    ) -> Task:
        deadline = None if timeout is None else time.monotonic() + timeout
        scoped_order = self._resolve_scan_order(allowed_event_types)
        if not scoped_order:
            raise Empty("MultiTaskQueue no allowed event types")

        while True:
            for event_type in self._next_scan_order(scoped_order):
                queue = self._sub_queues[event_type]
                try:
                    task = queue.get(timeout=self.SUBQUEUE_PROBE_TIMEOUT_SECONDS)
                except Empty:
                    continue
                with self._lock:
                    self._inflight_task_to_event[task.task_id] = event_type
                return task

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Empty("MultiTaskQueue get timeout")
                sleep_for = min(self._poll_interval_seconds, remaining)
            else:
                sleep_for = self._poll_interval_seconds
            time.sleep(max(sleep_for, 0.001))

    def task_done(self, task_id: str) -> None:
        with self._lock:
            event_type = self._inflight_task_to_event.pop(task_id, None)
        if event_type is None:
            return
        self._sub_queues[event_type].task_done(task_id)

    def qsize(self) -> int:
        return sum(queue.qsize() for queue in self._sub_queues.values())

    def join(self) -> None:
        for queue in self._sub_queues.values():
            queue.join()

    def _resolve_scan_order(self, allowed_event_types: set[EventType] | None) -> list[EventType]:
        if not allowed_event_types:
            return list(self._scan_order)
        return [event_type for event_type in self._scan_order if event_type in allowed_event_types]

    def _next_scan_order(self, scoped_order: list[EventType]) -> list[EventType]:
        scope_key = ",".join(event_type.value for event_type in scoped_order)
        size = len(scoped_order)
        if size == 0:
            return []
        with self._lock:
            start = self._next_scan_index_by_scope.get(scope_key, 0) % size
            self._next_scan_index_by_scope[scope_key] = (start + 1) % size
            return scoped_order[start:] + scoped_order[:start]
