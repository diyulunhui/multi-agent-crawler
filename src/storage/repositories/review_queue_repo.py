from __future__ import annotations

from src.domain.models import ReviewQueueItem
from src.storage.repositories.base_repo import BaseRepository


class ReviewQueueRepository(BaseRepository):
    def upsert_pending(self, item: ReviewQueueItem) -> None:
        # 低置信度任务入人工复核队列；同实体重复命中时更新为最新上下文。
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO review_queue (
                    review_id, queue_type, entity_type, entity_id, reason,
                    confidence_score, payload_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(queue_type, entity_type, entity_id) DO UPDATE SET
                    reason = excluded.reason,
                    confidence_score = excluded.confidence_score,
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    item.review_id,
                    item.queue_type,
                    item.entity_type,
                    item.entity_id,
                    item.reason,
                    self.decimal_to_db(item.confidence_score),
                    item.payload_json,
                    item.status,
                    self.dt_to_iso(item.created_at),
                    self.dt_to_iso(item.updated_at),
                ),
            )

    def resolve(self, queue_type: str, entity_type: str, entity_id: str) -> None:
        # 当清洗结果恢复高置信度时，自动把历史复核单标记为 resolved。
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE review_queue
                SET status = 'resolved',
                    updated_at = ?
                WHERE queue_type = ? AND entity_type = ? AND entity_id = ? AND status <> 'resolved'
                """,
                (self.now_iso(), queue_type, entity_type, entity_id),
            )

    def get_pending_by_entity(self, queue_type: str, entity_type: str, entity_id: str) -> ReviewQueueItem | None:
        # 查询指定实体的待处理复核记录。
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM review_queue
                WHERE queue_type = ? AND entity_type = ? AND entity_id = ? AND status = 'pending'
                LIMIT 1
                """,
                (queue_type, entity_type, entity_id),
            ).fetchone()
        if row is None:
            return None
        return ReviewQueueItem(
            review_id=row["review_id"],
            queue_type=row["queue_type"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            reason=row["reason"],
            confidence_score=self.db_to_decimal(row["confidence_score"]),  # type: ignore[arg-type]
            payload_json=row["payload_json"],
            status=row["status"],
            created_at=self.iso_to_dt(row["created_at"]),  # type: ignore[arg-type]
            updated_at=self.iso_to_dt(row["updated_at"]),  # type: ignore[arg-type]
        )
