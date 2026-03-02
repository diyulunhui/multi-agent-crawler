from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.domain.events import EventType, Task, TaskPriority, TaskStatus
from src.domain.models import TaskState
from src.queue.priority_queue import PriorityTaskQueue
from src.storage.repositories.task_repo import TaskRepository
from src.workers.retry_policy import ExponentialBackoffRetryPolicy


class RecoveryService:
    def __init__(
        self,
        task_repo: TaskRepository,
        queue: PriorityTaskQueue,
        retry_policy: ExponentialBackoffRetryPolicy,
    ) -> None:
        self.task_repo = task_repo
        self.queue = queue
        self.retry_policy = retry_policy

    def recover(self, limit: int = 500) -> int:
        # 重启恢复入口：回收 unfinished 任务并重新入队。
        states = self.task_repo.get_unfinished_tasks(limit=limit)
        requeue_count = 0

        for state in states:
            if state.status == TaskStatus.DEAD:
                continue

            if state.status == TaskStatus.FAILED:
                # failed 任务按退避策略延后重试。
                decision = self.retry_policy.decide(state.retry_count)
                if not decision.should_retry:
                    continue
                run_at = datetime.now(timezone.utc) + timedelta(seconds=decision.delay_seconds)
                task = self._state_to_task(state, run_at=run_at, retry_count=decision.next_retry_count)
                # 复用原 task_id，直接更新运行时间和重试计数，避免插入新行触发主键冲突。
                self.task_repo.schedule_retry(
                    task_id=task.task_id,
                    run_at_iso=task.run_at.isoformat(),
                    retry_count=task.retry_count,
                )
                self.queue.put(task)
                requeue_count += 1
                continue

            task = self._state_to_task(state)
            # pending/running 恢复时仅重置为 pending，并沿用原 task_id。
            self.task_repo.reset_to_pending(task_id=task.task_id, retry_count=task.retry_count)
            self.queue.put(task)
            requeue_count += 1

        return requeue_count

    @staticmethod
    def _state_to_task(
        state: TaskState,
        run_at: datetime | None = None,
        retry_count: int | None = None,
    ) -> Task:
        return Task(
            task_id=state.task_id,
            event_type=EventType(state.event_type),
            entity_id=state.entity_id,
            run_at=run_at or state.run_at,
            priority=TaskPriority(state.priority),
            payload=dict(state.payload),
            retry_count=retry_count if retry_count is not None else state.retry_count,
            max_retries=state.max_retries,
        )
