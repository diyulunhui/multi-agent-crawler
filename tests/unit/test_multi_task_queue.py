from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from queue import Empty

from src.domain.events import EventType, Task, TaskPriority
from src.queue.multi_task_queue import MultiTaskQueue


class MultiTaskQueueTestCase(unittest.TestCase):
    def test_due_task_not_blocked_by_future_final_monitor(self) -> None:
        # 未来 FINAL 任务不应阻塞已到期的发现任务。
        queue = MultiTaskQueue(max_size=128, poll_interval_seconds=0.01)
        now = datetime.now(timezone.utc)

        future_final = Task(
            event_type=EventType.SNAPSHOT_FINAL_MONITOR,
            entity_id="future_final",
            run_at=now + timedelta(minutes=10),
            priority=TaskPriority.FINAL_MONITOR,
        )
        due_discovery = Task(
            event_type=EventType.DISCOVER_SESSIONS,
            entity_id="due_discovery",
            run_at=now,
            priority=TaskPriority.DISCOVERY,
        )

        queue.put(future_final)
        queue.put(due_discovery)

        first = queue.get(timeout=0.5)
        self.assertEqual("due_discovery", first.entity_id)
        queue.task_done(first.task_id)

        with self.assertRaises(Empty):
            queue.get(timeout=0.05)

    def test_discovery_task_should_be_prioritized_over_structure_task(self) -> None:
        # 异步结构化不应抢占发现主链路。
        queue = MultiTaskQueue(max_size=128, poll_interval_seconds=0.01)
        now = datetime.now(timezone.utc)

        structure_task = Task(
            event_type=EventType.STRUCTURE_LOT,
            entity_id="lot_1",
            run_at=now,
            priority=TaskPriority.NEXTDAY_BACKFILL,
        )
        discovery_task = Task(
            event_type=EventType.DISCOVER_LOTS,
            entity_id="session_1",
            run_at=now,
            priority=TaskPriority.DISCOVERY,
        )

        queue.put(structure_task)
        queue.put(discovery_task)

        first = queue.get(timeout=0.5)
        self.assertEqual(EventType.DISCOVER_LOTS, first.event_type)
        queue.task_done(first.task_id)

    def test_allowed_event_types_should_route_to_dedicated_worker(self) -> None:
        # 专用 worker 拉取指定 event_type 时，应只拿对应任务。
        queue = MultiTaskQueue(max_size=128, poll_interval_seconds=0.01)
        now = datetime.now(timezone.utc)
        queue.put(
            Task(
                event_type=EventType.DISCOVER_LOTS,
                entity_id="session_d",
                run_at=now,
                priority=TaskPriority.DISCOVERY,
            )
        )
        queue.put(
            Task(
                event_type=EventType.STRUCTURE_LOT,
                entity_id="lot_s",
                run_at=now,
                priority=TaskPriority.NEXTDAY_BACKFILL,
            )
        )

        structure_task = queue.get(timeout=0.5, allowed_event_types={EventType.STRUCTURE_LOT})
        self.assertEqual(EventType.STRUCTURE_LOT, structure_task.event_type)
        queue.task_done(structure_task.task_id)

        main_task = queue.get(timeout=0.5, allowed_event_types={EventType.DISCOVER_LOTS})
        self.assertEqual(EventType.DISCOVER_LOTS, main_task.event_type)
        queue.task_done(main_task.task_id)


if __name__ == "__main__":
    unittest.main()
