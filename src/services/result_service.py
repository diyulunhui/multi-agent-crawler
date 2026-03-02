from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.storage.db import Database


class ResultService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_from_snapshot(
        self,
        lot_id: str,
        final_price: Decimal | None,
        final_end_time: datetime | None,
        confidence_score: Decimal,
        decided_from_snapshot: str,
        is_unsold: bool = False,
        is_withdrawn: bool = False,
    ) -> None:
        # 结果写入采用“置信度优先 + 终态保护”：
        # 1) 低置信度的空值更新不会覆盖已确认成交价；
        # 2) 高置信度且明确终态（流拍/撤拍）时允许将价格置空；
        # 3) 非空结束时间只增不减，避免被后续轮询清空。
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO lot_result (
                    lot_id, final_price, final_end_time,
                    is_withdrawn, is_unsold,
                    confidence_score, decided_from_snapshot, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lot_id) DO UPDATE SET
                    final_price = CASE
                        WHEN excluded.final_price IS NOT NULL THEN excluded.final_price
                        WHEN (excluded.is_unsold = 1 OR excluded.is_withdrawn = 1)
                          AND excluded.confidence_score >= lot_result.confidence_score THEN NULL
                        ELSE lot_result.final_price
                    END,
                    final_end_time = COALESCE(excluded.final_end_time, lot_result.final_end_time),
                    is_withdrawn = CASE
                        WHEN excluded.confidence_score >= lot_result.confidence_score THEN excluded.is_withdrawn
                        ELSE lot_result.is_withdrawn
                    END,
                    is_unsold = CASE
                        WHEN excluded.confidence_score >= lot_result.confidence_score THEN excluded.is_unsold
                        ELSE lot_result.is_unsold
                    END,
                    confidence_score = MAX(lot_result.confidence_score, excluded.confidence_score),
                    decided_from_snapshot = CASE
                        WHEN excluded.confidence_score >= lot_result.confidence_score
                            THEN excluded.decided_from_snapshot
                        ELSE lot_result.decided_from_snapshot
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    lot_id,
                    float(final_price) if final_price is not None else None,
                    final_end_time.astimezone(timezone.utc).isoformat() if final_end_time else None,
                    1 if is_withdrawn else 0,
                    1 if is_unsold else 0,
                    float(confidence_score),
                    decided_from_snapshot,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
