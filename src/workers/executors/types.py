from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutorResult:
    # 执行器统一返回结构，便于 WorkerPool 统计。
    success: bool
    processed_count: int = 0
    emitted_task_count: int = 0
    message: str = ""
