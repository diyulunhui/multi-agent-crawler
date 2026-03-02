from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.config.settings import AppConfig
from src.storage.db import Database
from src.storage.repositories.review_queue_repo import ReviewQueueRepository
from src.domain.models import ReviewQueueItem


class ReviewQueueRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 准备独立测试数据库。
        cfg = AppConfig.from_env()
        self.config = replace(cfg, db_url="sqlite:///data/test_review_queue.db")

        db_path = Path("data/test_review_queue.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()

    def test_upsert_pending_and_resolve(self) -> None:
        # 先写入 pending，再执行 resolve，确认状态流转正确。
        repo = ReviewQueueRepository(self.db)
        now = datetime.now(timezone.utc)
        repo.upsert_pending(
            ReviewQueueItem(
                review_id="review_structured_l1",
                queue_type="STRUCTURED_CLEANING",
                entity_type="lot",
                entity_id="l1",
                reason="置信度偏低",
                confidence_score=Decimal("0.45"),
                payload_json='{"lot_id":"l1"}',
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
        pending = repo.get_pending_by_entity("STRUCTURED_CLEANING", "lot", "l1")
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual("pending", pending.status)

        repo.resolve(queue_type="STRUCTURED_CLEANING", entity_type="lot", entity_id="l1")
        pending_after = repo.get_pending_by_entity("STRUCTURED_CLEANING", "lot", "l1")
        self.assertIsNone(pending_after)

    def test_upsert_pending_updates_existing_row(self) -> None:
        # 同一实体重复入队时应覆盖原因与上下文，而不是新增重复记录。
        repo = ReviewQueueRepository(self.db)
        now = datetime.now(timezone.utc)
        first = ReviewQueueItem(
            review_id="review_structured_l2",
            queue_type="STRUCTURED_CLEANING",
            entity_type="lot",
            entity_id="l2",
            reason="初次入队",
            confidence_score=Decimal("0.50"),
            payload_json='{"v":1}',
            status="pending",
            created_at=now,
            updated_at=now,
        )
        second = ReviewQueueItem(
            review_id="review_structured_l2",
            queue_type="STRUCTURED_CLEANING",
            entity_type="lot",
            entity_id="l2",
            reason="二次覆盖",
            confidence_score=Decimal("0.42"),
            payload_json='{"v":2}',
            status="pending",
            created_at=now,
            updated_at=now,
        )
        repo.upsert_pending(first)
        repo.upsert_pending(second)

        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT reason, confidence_score, payload_json, COUNT(1) OVER() AS total
                FROM review_queue
                WHERE queue_type='STRUCTURED_CLEANING' AND entity_type='lot' AND entity_id='l2'
                """,
            ).fetchone()
        self.assertEqual("二次覆盖", row["reason"])
        self.assertEqual(0.42, row["confidence_score"])
        self.assertEqual('{"v":2}', row["payload_json"])
        self.assertEqual(1, row["total"])


if __name__ == "__main__":
    unittest.main()
