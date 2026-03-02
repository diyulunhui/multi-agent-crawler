from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.storage.db import Database


@dataclass
class ConflictIssue:
    # 跨快照冲突记录。
    lot_id: str
    field: str
    values: list[str]


@dataclass
class QualityScore:
    # 快照质量评分结构。
    lot_id: str
    score: Decimal
    reasons: list[str]


class QualityService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def evaluate_snapshot(self, lot_id: str, current_price, bid_count) -> QualityScore:
        # 基础规则：缺失价格、负数价格、无效 bid_count 均扣分。
        score = Decimal("1.0")
        reasons: list[str] = []

        if current_price is None:
            score -= Decimal("0.4")
            reasons.append("缺失价格")
        elif current_price < 0:
            score -= Decimal("0.6")
            reasons.append("价格为负数")

        if bid_count is not None and bid_count < 0:
            score -= Decimal("0.3")
            reasons.append("出价次数为负")

        if score < Decimal("0"):
            score = Decimal("0")

        return QualityScore(lot_id=lot_id, score=score, reasons=reasons)

    def detect_conflicts(self, lot_id: str) -> list[ConflictIssue]:
        # 检测同一 lot 在不同快照类型中的价格冲突。
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_type, current_price
                FROM lot_snapshot
                WHERE lot_id = ? AND current_price IS NOT NULL
                """,
                (lot_id,),
            ).fetchall()

        values = {}
        for row in rows:
            values.setdefault(str(row["current_price"]), []).append(row["snapshot_type"])

        if len(values) <= 1:
            return []

        conflict_values = [f"{price}:{','.join(types)}" for price, types in values.items()]
        return [ConflictIssue(lot_id=lot_id, field="current_price", values=conflict_values)]

    def update_snapshot_quality(self, lot_id: str, snapshot_type: str, quality_score: Decimal) -> None:
        # 将质量分写回最近一条指定快照。
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE lot_snapshot
                SET quality_score = ?
                WHERE snapshot_id = (
                    SELECT snapshot_id
                    FROM lot_snapshot
                    WHERE lot_id = ? AND snapshot_type = ?
                    ORDER BY snapshot_time DESC
                    LIMIT 1
                )
                """,
                (float(quality_score), lot_id, snapshot_type),
            )
