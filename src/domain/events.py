from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class SessionType(str, Enum):
    # 场次类型：专场 / 普通拍卖。
    SPECIAL = "SPECIAL"
    NORMAL = "NORMAL"


class SnapshotType(str, Enum):
    # 快照类型：T-5、T-1、最终监控、次日修正。
    PRE5 = "PRE5"
    PRE1 = "PRE1"
    FINAL = "FINAL"
    NEXTDAY_FIX = "NEXTDAY_FIX"


class EventType(str, Enum):
    # 任务事件类型，作为调度和执行路由键。
    DISCOVER_SESSIONS = "DISCOVER_SESSIONS"
    DISCOVER_LOTS = "DISCOVER_LOTS"
    STRUCTURE_LOT = "STRUCTURE_LOT"
    SNAPSHOT_PRE5 = "SNAPSHOT_PRE5"
    SNAPSHOT_PRE1 = "SNAPSHOT_PRE1"
    SNAPSHOT_FINAL_MONITOR = "SNAPSHOT_FINAL_MONITOR"
    SESSION_FINAL_SCRAPE = "SESSION_FINAL_SCRAPE"


class TaskStatus(str, Enum):
    # 任务生命周期状态。
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


class TaskPriority(int, Enum):
    # 数值越小优先级越高。
    PRE5 = 10
    PRE1 = 20
    FINAL_MONITOR = 30
    DISCOVERY = 40
    NEXTDAY_BACKFILL = 50


@dataclass(order=True)
class PrioritizedTask:
    # PriorityQueue 使用的可排序任务包装。
    priority: int
    run_at_ts: float
    task_id: str = field(compare=False)
    task: "Task" = field(compare=False)


@dataclass
class Task:
    # 运行时任务对象，包含幂等键和重试参数。
    event_type: EventType
    entity_id: str
    run_at: datetime
    priority: TaskPriority
    payload: dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: f"task_{uuid4().hex}")
    retry_count: int = 0
    max_retries: int = 3

    def dedupe_key(self) -> str:
        # 按事件语义生成幂等键，避免重复发现任务无限膨胀队列。
        # - 发现/结构化：同一实体同类任务只保留一条
        # - 专场补抓：按 stage 区分 POST_CLOSE / NEXTDAY_FIX / D3_BACKFILL
        # - 快照任务：按 snapshot_type 区分 PRE5 / PRE1 / FINAL
        if self.event_type in {
            EventType.DISCOVER_SESSIONS,
            EventType.DISCOVER_LOTS,
            EventType.STRUCTURE_LOT,
        }:
            return f"{self.event_type.value}:{self.entity_id}"

        if self.event_type == EventType.SESSION_FINAL_SCRAPE:
            stage = str(self.payload.get("stage") or "")
            return f"{self.event_type.value}:{self.entity_id}:{stage}"

        if self.event_type in {
            EventType.SNAPSHOT_PRE5,
            EventType.SNAPSHOT_PRE1,
            EventType.SNAPSHOT_FINAL_MONITOR,
        }:
            snapshot_type = str(self.payload.get("snapshot_type") or self.event_type.value)
            return f"{self.event_type.value}:{self.entity_id}:{snapshot_type}"

        return f"{self.event_type.value}:{self.entity_id}:{int(self.run_at.timestamp())}"

    def to_prioritized(self) -> PrioritizedTask:
        # 统一转换为 UTC 时间戳，保证跨时区排序一致。
        run_at_utc = self.run_at.astimezone(timezone.utc)
        return PrioritizedTask(
            priority=int(self.priority),
            run_at_ts=run_at_utc.timestamp(),
            task_id=self.task_id,
            task=self,
        )
