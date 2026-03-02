from __future__ import annotations

from datetime import datetime, timezone

from src.domain.models import Lot
from src.storage.repositories.base_repo import BaseRepository


class LotRepository(BaseRepository):
    def upsert_lot(self, lot: Lot) -> None:
        # 标的增量更新：同 lot_id 覆盖最新观测字段与时间戳。
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO lot (
                    lot_id, session_id, title_raw, description_raw, category, grade_agency, grade_score,
                    end_time, status, last_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lot_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    title_raw = excluded.title_raw,
                    description_raw = excluded.description_raw,
                    category = excluded.category,
                    grade_agency = excluded.grade_agency,
                    grade_score = excluded.grade_score,
                    end_time = excluded.end_time,
                    status = excluded.status,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (
                    lot.lot_id,
                    lot.session_id,
                    lot.title_raw,
                    lot.description_raw,
                    lot.category,
                    lot.grade_agency,
                    lot.grade_score,
                    self.dt_to_iso(lot.end_time),
                    lot.status,
                    self.dt_to_iso(lot.last_seen_at),
                    self.dt_to_iso(lot.updated_at),
                ),
            )

    def get_by_id(self, lot_id: str) -> Lot | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lot WHERE lot_id = ?", (lot_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_lot(row)

    def list_by_session(self, session_id: str) -> list[Lot]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lot WHERE session_id = ? ORDER BY end_time ASC", (session_id,)
            ).fetchall()
        return [self._row_to_lot(row) for row in rows]

    def list_due_for_pre5(self, now_iso: str, limit: int = 500) -> list[Lot]:
        # 查询已达到 PRE5 调度窗口的进行中标的。
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM lot
                WHERE status = 'bidding'
                  AND end_time IS NOT NULL
                  AND end_time <= ?
                ORDER BY end_time ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
        return [self._row_to_lot(row) for row in rows]

    @staticmethod
    def new(lot_id: str, session_id: str, title_raw: str, end_time: datetime | None) -> Lot:
        # 发现阶段快速创建 Lot 对象的便捷方法。
        now = datetime.now(timezone.utc)
        return Lot(
            lot_id=lot_id,
            session_id=session_id,
            title_raw=title_raw,
            description_raw=None,
            category=None,
            grade_agency=None,
            grade_score=None,
            end_time=end_time,
            status="bidding",
            last_seen_at=now,
            updated_at=now,
        )

    def _row_to_lot(self, row) -> Lot:
        return Lot(
            lot_id=row["lot_id"],
            session_id=row["session_id"],
            title_raw=row["title_raw"],
            description_raw=row["description_raw"],
            category=row["category"],
            grade_agency=row["grade_agency"],
            grade_score=row["grade_score"],
            end_time=self.iso_to_dt(row["end_time"]),
            status=row["status"],
            last_seen_at=self.iso_to_dt(row["last_seen_at"]),
            updated_at=self.iso_to_dt(row["updated_at"]),
        )
