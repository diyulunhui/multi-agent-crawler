from __future__ import annotations

import json
from typing import Iterable

from src.domain.events import EventType, Task, TaskStatus
from src.domain.models import TaskState
from src.storage.repositories.base_repo import BaseRepository


class TaskRepository(BaseRepository):
    def upsert_task(self, task: Task) -> None:
        # 基于 dedupe_key 幂等写入任务，重复任务只刷新关键字段。
        now = self.now_iso()
        payload_json = json.dumps(task.payload, ensure_ascii=False, sort_keys=True)
        dedupe_key = task.dedupe_key()
        with self.db.connection() as conn:
            # 先按 task_id 更新，兼容历史 dedupe 规则调整后的老任务行。
            updated = conn.execute(
                """
                UPDATE task_state
                SET event_type = ?, entity_id = ?, run_at = ?, priority = ?, status = ?,
                    retry_count = ?, max_retries = ?, last_error = ?, payload_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    task.event_type.value,
                    task.entity_id,
                    self.dt_to_iso(task.run_at),
                    int(task.priority),
                    TaskStatus.PENDING.value,
                    task.retry_count,
                    task.max_retries,
                    None,
                    payload_json,
                    now,
                    task.task_id,
                ),
            )
            if updated.rowcount:
                return

            conn.execute(
                """
                INSERT INTO task_state (
                    task_id, event_type, entity_id, run_at, priority, status,
                    retry_count, max_retries, last_error, dedupe_key, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    task_id=excluded.task_id,
                    run_at=excluded.run_at,
                    priority=excluded.priority,
                    status=excluded.status,
                    retry_count=excluded.retry_count,
                    max_retries=excluded.max_retries,
                    last_error=excluded.last_error,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    task.task_id,
                    task.event_type.value,
                    task.entity_id,
                    self.dt_to_iso(task.run_at),
                    int(task.priority),
                    TaskStatus.PENDING.value,
                    task.retry_count,
                    task.max_retries,
                    None,
                    dedupe_key,
                    payload_json,
                    now,
                ),
            )

    def get_due_pending_tasks(self, now_iso: str, limit: int = 200) -> list[TaskState]:
        # 获取当前到期且待执行的任务。
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_state
                WHERE status = ? AND run_at <= ?
                ORDER BY priority ASC, run_at ASC
                LIMIT ?
                """,
                (TaskStatus.PENDING.value, now_iso, limit),
            ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def get_unfinished_tasks(self, limit: int = 500) -> list[TaskState]:
        # 用于重启恢复：提取 pending/running/failed 任务。
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_state
                WHERE status IN (?, ?, ?)
                ORDER BY run_at ASC
                LIMIT ?
                """,
                (
                    TaskStatus.PENDING.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.FAILED.value,
                    limit,
                ),
            ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def get_by_task_id(self, task_id: str) -> TaskState | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM task_state WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_state(row)

    def mark_running(self, task_id: str) -> None:
        self._set_status(task_id, TaskStatus.RUNNING, None)

    def mark_succeeded(self, task_id: str) -> None:
        self._set_status(task_id, TaskStatus.SUCCEEDED, None)

    def mark_failed(self, task_id: str, error: str, retry_count: int, max_retries: int) -> TaskStatus:
        # 达到上限标记 dead，否则标记 failed 等待恢复服务处理。
        status = TaskStatus.FAILED if retry_count < max_retries else TaskStatus.DEAD
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE task_state
                SET status = ?, retry_count = ?, last_error = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (status.value, retry_count, error[:1000], self.now_iso(), task_id),
            )
        return status

    def reset_to_pending(self, task_id: str, retry_count: int) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE task_state
                SET status = ?, retry_count = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (TaskStatus.PENDING.value, retry_count, self.now_iso(), task_id),
            )

    def schedule_retry(self, task_id: str, run_at_iso: str, retry_count: int) -> None:
        # 在同一 task_id 上重排执行时间并恢复为 pending。
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE task_state
                SET run_at = ?, retry_count = ?, status = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (run_at_iso, retry_count, TaskStatus.PENDING.value, self.now_iso(), task_id),
            )

    def bulk_requeue(self, states: Iterable[TaskState]) -> int:
        count = 0
        with self.db.connection() as conn:
            for state in states:
                conn.execute(
                    """
                    UPDATE task_state
                    SET status = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (TaskStatus.PENDING.value, self.now_iso(), state.task_id),
                )
                count += 1
        return count

    def _set_status(self, task_id: str, status: TaskStatus, last_error: str | None) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE task_state
                SET status = ?, last_error = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (status.value, last_error, self.now_iso(), task_id),
            )

    def _row_to_state(self, row) -> TaskState:
        # 数据库行转领域对象，保持上层逻辑无 SQL 依赖。
        return TaskState(
            task_id=row["task_id"],
            event_type=EventType(row["event_type"]),
            entity_id=row["entity_id"],
            run_at=self.iso_to_dt(row["run_at"]),  # type: ignore[arg-type]
            priority=row["priority"],
            status=TaskStatus(row["status"]),
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            last_error=row["last_error"],
            dedupe_key=row["dedupe_key"],
            payload=self._parse_payload_json(row["payload_json"]),
            updated_at=self.iso_to_dt(row["updated_at"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _parse_payload_json(value: object) -> dict:
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
