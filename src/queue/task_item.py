from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.domain.events import EventType, PrioritizedTask, Task


@dataclass(frozen=True)
class TaskQueueItem:
    # 队列元素包装，便于集中处理到期判断逻辑。
    prioritized: PrioritizedTask

    @property
    def task(self) -> Task:
        return self.prioritized.task

    @property
    def run_at(self) -> datetime:
        return datetime.fromtimestamp(self.prioritized.run_at_ts, tz=timezone.utc)

    @property
    def ready(self) -> bool:
        # 判断任务是否到达执行时间。
        return self.run_at <= datetime.now(timezone.utc)

    @staticmethod
    def from_task(task: Task) -> "TaskQueueItem":
        prioritized = task.to_prioritized()
        effective_priority = TaskQueueItem._effective_priority(task)
        if effective_priority != prioritized.priority:
            prioritized = PrioritizedTask(
                priority=effective_priority,
                run_at_ts=prioritized.run_at_ts,
                task_id=prioritized.task_id,
                task=prioritized.task,
            )
        return TaskQueueItem(prioritized=prioritized)

    @staticmethod
    def _effective_priority(task: Task) -> int:
        # 线上执行优先级：FINAL 优先，避免被 PRE5 队列长期饿死。
        if task.event_type == EventType.SNAPSHOT_FINAL_MONITOR:
            return 8
        if task.event_type in {EventType.SNAPSHOT_PRE5, EventType.SNAPSHOT_PRE1}:
            return 20
        return int(task.priority)
