from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.storage.db import Database


@dataclass
class DriftAlert:
    # 页面解析漂移告警结构。
    site: str
    window_minutes: int
    total_count: int
    failed_count: int
    failure_rate: float
    threshold: float


class DriftDetector:
    def __init__(self, db: Database) -> None:
        self.db = db

    def detect(
        self,
        site: str,
        window_minutes: int = 30,
        min_samples: int = 10,
        failure_threshold: float = 0.30,
    ) -> DriftAlert | None:
        # 通过 task_state 的失败率检测解析漂移。
        start = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        start_iso = start.isoformat()

        with self.db.connection() as conn:
            total = conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM task_state
                WHERE event_type IN ('DISCOVER_SESSIONS', 'DISCOVER_LOTS')
                  AND updated_at >= ?
                """,
                (start_iso,),
            ).fetchone()["c"]

            failed = conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM task_state
                WHERE event_type IN ('DISCOVER_SESSIONS', 'DISCOVER_LOTS')
                  AND status IN ('failed', 'dead')
                  AND updated_at >= ?
                """,
                (start_iso,),
            ).fetchone()["c"]

        if total < min_samples:
            return None

        failure_rate = failed / total
        if failure_rate < failure_threshold:
            return None

        return DriftAlert(
            site=site,
            window_minutes=window_minutes,
            total_count=int(total),
            failed_count=int(failed),
            failure_rate=failure_rate,
            threshold=failure_threshold,
        )
