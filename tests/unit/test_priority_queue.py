from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from queue import Empty

from src.domain.events import EventType, Task, TaskPriority
from src.queue.priority_queue import PriorityTaskQueue


class PriorityQueueTestCase(unittest.TestCase):
    def test_priority_order(self) -> None:
        # 高优先级任务应先于低优先级任务执行。
        q = PriorityTaskQueue(poll_interval_seconds=0.01)
        now = datetime.now(timezone.utc)

        low = Task(
            event_type=EventType.DISCOVER_SESSIONS,
            entity_id="low",
            run_at=now,
            priority=TaskPriority.DISCOVERY,
        )
        high = Task(
            event_type=EventType.SNAPSHOT_PRE5,
            entity_id="high",
            run_at=now,
            priority=TaskPriority.PRE5,
        )

        q.put(low)
        q.put(high)

        first = q.get(timeout=1)
        self.assertEqual("high", first.entity_id)
        q.task_done(first.task_id)

        second = q.get(timeout=1)
        self.assertEqual("low", second.entity_id)
        q.task_done(second.task_id)

    def test_delay_respected(self) -> None:
        # 未到期任务不应立刻返回。
        q = PriorityTaskQueue(poll_interval_seconds=0.01)
        delayed = Task(
            event_type=EventType.SNAPSHOT_PRE5,
            entity_id="delayed",
            run_at=datetime.now(timezone.utc) + timedelta(seconds=0.2),
            priority=TaskPriority.PRE5,
        )
        q.put(delayed)

        with self.assertRaises(Empty):
            q.get(timeout=0.05)

    def test_final_monitor_prioritized_over_pre5(self) -> None:
        # 运行时调度应优先消费 FINAL，保证成交结果尽快产出。
        q = PriorityTaskQueue(poll_interval_seconds=0.01)
        now = datetime.now(timezone.utc)
        pre5 = Task(
            event_type=EventType.SNAPSHOT_PRE5,
            entity_id="pre5",
            run_at=now,
            priority=TaskPriority.PRE5,
        )
        final = Task(
            event_type=EventType.SNAPSHOT_FINAL_MONITOR,
            entity_id="final",
            run_at=now,
            priority=TaskPriority.FINAL_MONITOR,
        )
        q.put(pre5)
        q.put(final)

        first = q.get(timeout=1)
        self.assertEqual("final", first.entity_id)
        q.task_done(first.task_id)

        second = q.get(timeout=1)
        self.assertEqual("pre5", second.entity_id)
        q.task_done(second.task_id)


if __name__ == "__main__":
    unittest.main()
