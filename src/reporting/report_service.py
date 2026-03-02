from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.storage.db import Database


@dataclass
class ReportRow:
    # 聚合报表单行结构。
    site: str
    session_id: str
    category: str
    lot_count: int
    avg_price: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None
    avg_confidence: Decimal


@dataclass
class DailyReport:
    # 日报结构，包含数据窗口与质量摘要。
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    rows: list[ReportRow]
    quality_summary: dict[str, float]


class ReportService:
    def __init__(self, db: Database, site_name: str) -> None:
        self.db = db
        self.site_name = site_name

    def build_daily_report(self, day: datetime | None = None) -> DailyReport:
        # 默认统计 UTC 当天窗口。
        day = day or datetime.now(timezone.utc)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    l.session_id AS session_id,
                    COALESCE(l.category, 'unknown') AS category,
                    COUNT(1) AS lot_count,
                    AVG(r.final_price) AS avg_price,
                    MIN(r.final_price) AS min_price,
                    MAX(r.final_price) AS max_price,
                    AVG(r.confidence_score) AS avg_confidence
                FROM lot_result r
                JOIN lot l ON l.lot_id = r.lot_id
                WHERE r.updated_at >= ? AND r.updated_at < ?
                GROUP BY l.session_id, COALESCE(l.category, 'unknown')
                ORDER BY lot_count DESC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()

            quality = conn.execute(
                """
                SELECT
                    AVG(confidence_score) AS avg_confidence,
                    SUM(CASE WHEN confidence_score < 0.7 THEN 1 ELSE 0 END) AS low_conf_count,
                    COUNT(1) AS total_count
                FROM lot_result
                WHERE updated_at >= ? AND updated_at < ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchone()

        report_rows = [
            ReportRow(
                site=self.site_name,
                session_id=row["session_id"],
                category=row["category"],
                lot_count=int(row["lot_count"]),
                avg_price=Decimal(str(row["avg_price"])) if row["avg_price"] is not None else None,
                min_price=Decimal(str(row["min_price"])) if row["min_price"] is not None else None,
                max_price=Decimal(str(row["max_price"])) if row["max_price"] is not None else None,
                avg_confidence=Decimal(str(row["avg_confidence"] or 0)),
            )
            for row in rows
        ]

        quality_summary = {
            "avg_confidence": float(quality["avg_confidence"] or 0),
            "low_conf_count": float(quality["low_conf_count"] or 0),
            "total_count": float(quality["total_count"] or 0),
        }

        return DailyReport(
            generated_at=datetime.now(timezone.utc),
            window_start=start,
            window_end=end,
            rows=report_rows,
            quality_summary=quality_summary,
        )
