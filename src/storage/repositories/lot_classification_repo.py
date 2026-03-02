from __future__ import annotations

from src.domain.models import LotClassification
from src.storage.repositories.base_repo import BaseRepository


class LotClassificationRepository(BaseRepository):
    def upsert_classification(self, classification: LotClassification) -> None:
        # 分类结果按 lot_id 幂等覆盖，保证规则升级后可重跑刷新。
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO lot_classification (
                    lot_id, category_l1, category_l2, tags_json,
                    rule_hit, confidence_score, classifier_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lot_id) DO UPDATE SET
                    category_l1 = excluded.category_l1,
                    category_l2 = excluded.category_l2,
                    tags_json = excluded.tags_json,
                    rule_hit = excluded.rule_hit,
                    confidence_score = excluded.confidence_score,
                    classifier_version = excluded.classifier_version,
                    updated_at = excluded.updated_at
                """,
                (
                    classification.lot_id,
                    classification.category_l1,
                    classification.category_l2,
                    classification.tags_json,
                    classification.rule_hit,
                    self.decimal_to_db(classification.confidence_score),
                    classification.classifier_version,
                    self.dt_to_iso(classification.updated_at),
                ),
            )

    def get_by_lot_id(self, lot_id: str) -> LotClassification | None:
        # 按拍品编号读取分类结果。
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lot_classification WHERE lot_id = ?", (lot_id,)).fetchone()
        if row is None:
            return None
        return LotClassification(
            lot_id=row["lot_id"],
            category_l1=row["category_l1"],
            category_l2=row["category_l2"],
            tags_json=row["tags_json"],
            rule_hit=row["rule_hit"],
            confidence_score=self.db_to_decimal(row["confidence_score"]),  # type: ignore[arg-type]
            classifier_version=row["classifier_version"],
            updated_at=self.iso_to_dt(row["updated_at"]),  # type: ignore[arg-type]
        )
