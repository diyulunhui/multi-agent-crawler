from __future__ import annotations

from src.domain.models import LotStructured
from src.storage.repositories.base_repo import BaseRepository


class LotStructuredRepository(BaseRepository):
    def upsert_structured(self, structured: LotStructured) -> None:
        # 结构化清洗结果按 lot_id 幂等覆盖，支持规则升级后重跑刷新。
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO lot_structured (
                    lot_id, coin_type, variety, mint_year, grading_company,
                    grade_score, denomination, special_tags_json, confidence_score,
                    extract_source, schema_version, raw_structured_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lot_id) DO UPDATE SET
                    coin_type = excluded.coin_type,
                    variety = excluded.variety,
                    mint_year = excluded.mint_year,
                    grading_company = excluded.grading_company,
                    grade_score = excluded.grade_score,
                    denomination = excluded.denomination,
                    special_tags_json = excluded.special_tags_json,
                    confidence_score = excluded.confidence_score,
                    extract_source = excluded.extract_source,
                    schema_version = excluded.schema_version,
                    raw_structured_json = excluded.raw_structured_json,
                    updated_at = excluded.updated_at
                """,
                (
                    structured.lot_id,
                    structured.coin_type,
                    structured.variety,
                    structured.mint_year,
                    structured.grading_company,
                    structured.grade_score,
                    structured.denomination,
                    structured.special_tags_json,
                    self.decimal_to_db(structured.confidence_score),
                    structured.extract_source,
                    structured.schema_version,
                    structured.raw_structured_json,
                    self.dt_to_iso(structured.updated_at),
                ),
            )

    def get_by_lot_id(self, lot_id: str) -> LotStructured | None:
        # 按拍品编号读取结构化清洗结果。
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lot_structured WHERE lot_id = ?", (lot_id,)).fetchone()
        if row is None:
            return None
        return LotStructured(
            lot_id=row["lot_id"],
            coin_type=row["coin_type"],
            variety=row["variety"],
            mint_year=row["mint_year"],
            grading_company=row["grading_company"],
            grade_score=row["grade_score"],
            denomination=row["denomination"],
            special_tags_json=row["special_tags_json"],
            confidence_score=self.db_to_decimal(row["confidence_score"]),  # type: ignore[arg-type]
            extract_source=row["extract_source"],
            schema_version=row["schema_version"],
            raw_structured_json=row["raw_structured_json"],
            updated_at=self.iso_to_dt(row["updated_at"]),  # type: ignore[arg-type]
        )
