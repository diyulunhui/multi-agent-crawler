from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from src.config.settings import AppConfig
from src.domain.events import EventType, Task, TaskPriority, TaskStatus
from src.domain.models import AuctionSession, Lot, TaskState
from src.queue.priority_queue import PriorityTaskQueue
from src.scheduler.policies import SchedulePolicy, ScheduledEvent
from src.storage.repositories.task_repo import TaskRepository


class TaskScheduler:
    def __init__(
        self,
        config: AppConfig,
        task_repo: TaskRepository,
        queue: PriorityTaskQueue | None = None,
    ) -> None:
        self.config = config
        self.policy = SchedulePolicy(config)
        self.task_repo = task_repo
        self.queue = queue

    def schedule_discovery(self, now: datetime | None = None, entry_url: str | None = None) -> list[Task]:
        # 调度发现任务并落库/入队。
        now = now or datetime.now(timezone.utc)
        if entry_url:
            return self._emit(
                [
                    ScheduledEvent(
                        event_type=EventType.DISCOVER_SESSIONS,
                        entity_id=self.config.site_name,
                        run_at=now,
                        priority=TaskPriority.DISCOVERY,
                        payload={"site": self.config.site_name, "url": entry_url},
                    )
                ]
            )
        return self._emit(self.policy.discovery_events(now))

    def schedule_discover_lots(
        self,
        session_id: str,
        source_url: str,
        now: datetime | None = None,
    ) -> list[Task]:
        # 为专场派发 DISCOVER_LOTS 任务。
        now = now or datetime.now(timezone.utc)
        return self._emit(
            [
                ScheduledEvent(
                    event_type=EventType.DISCOVER_LOTS,
                    entity_id=session_id,
                    run_at=now,
                    priority=TaskPriority.DISCOVERY,
                    payload={"session_id": session_id, "url": source_url},
                )
            ]
        )

    def schedule_lot_snapshots(self, lot: Lot, now: datetime | None = None) -> list[Task]:
        # 调度单个标的的快照任务。
        now = now or datetime.now(timezone.utc)
        return self.schedule_lot_snapshots_with_payload(lot, now=now, extra_payload=None)

    def schedule_lot_snapshots_with_payload(
        self,
        lot: Lot,
        now: datetime | None = None,
        extra_payload: dict | None = None,
    ) -> list[Task]:
        # 允许调用方透传 url 等上下文到快照任务载荷。
        now = now or datetime.now(timezone.utc)
        events = self.policy.lot_events(lot, now)
        if extra_payload:
            events = [
                ScheduledEvent(
                    event_type=e.event_type,
                    entity_id=e.entity_id,
                    run_at=e.run_at,
                    priority=e.priority,
                    payload={**e.payload, **extra_payload},
                )
                for e in events
            ]
        return self._emit(events)

    def schedule_lot_structuring(self, lot_id: str, now: datetime | None = None) -> list[Task]:
        # 结构化清洗改为异步任务，避免 DISCOVER_LOTS 同步等待大模型导致阻塞。
        now = now or datetime.now(timezone.utc)
        return self._emit(
            [
                ScheduledEvent(
                    event_type=EventType.STRUCTURE_LOT,
                    entity_id=lot_id,
                    run_at=now,
                    priority=TaskPriority.NEXTDAY_BACKFILL,
                    payload={"lot_id": lot_id},
                )
            ]
        )

    def schedule_session_scrapes(self, session: AuctionSession, now: datetime | None = None) -> list[Task]:
        # 调度专场分段补抓任务。
        now = now or datetime.now(timezone.utc)
        return self._emit(self.policy.session_events(session, now))

    def recover_unfinished_tasks(self, limit: int = 500) -> list[Task]:
        # 从 task_state 恢复可继续执行的任务。
        states = self.task_repo.get_unfinished_tasks(limit=limit)
        recovered: list[Task] = []

        for state in states:
            if state.status == TaskStatus.DEAD:
                continue
            if state.status == TaskStatus.FAILED and state.retry_count >= state.max_retries:
                continue
            recovered.append(self._state_to_task(state))

        for task in recovered:
            self.task_repo.upsert_task(task)
            if self.queue is not None:
                self.queue.put(task)

        return recovered

    def _emit(self, events: Iterable[ScheduledEvent]) -> list[Task]:
        # 将规则事件转为 Task，并持久化后放入队列。
        tasks: list[Task] = []
        for event in events:
            task = Task(
                event_type=event.event_type,
                entity_id=event.entity_id,
                run_at=event.run_at.astimezone(timezone.utc),
                priority=event.priority,
                payload=event.payload,
                max_retries=self.config.retry.max_retries,
            )
            self.task_repo.upsert_task(task)
            if self.queue is not None:
                self.queue.put(task)
            tasks.append(task)
        return tasks

    @staticmethod
    def _state_to_task(state: TaskState) -> Task:
        priority = TaskPriority(state.priority)
        return Task(
            task_id=state.task_id,
            event_type=EventType(state.event_type),
            entity_id=state.entity_id,
            run_at=state.run_at,
            priority=priority,
            payload=dict(state.payload),
            retry_count=state.retry_count,
            max_retries=state.max_retries,
        )
