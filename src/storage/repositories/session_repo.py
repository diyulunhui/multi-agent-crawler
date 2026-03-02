from __future__ import annotations

from datetime import datetime, timezone

from src.domain.events import SessionType
from src.domain.models import AuctionSession
from src.storage.repositories.base_repo import BaseRepository


class SessionRepository(BaseRepository):
    def upsert_session(self, session: AuctionSession) -> None:
        # 专场增量更新：主键冲突时覆盖可变字段。
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO auction_session (
                    session_id, session_type, title, scheduled_end_time,
                    source_url, discovered_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    session_type = excluded.session_type,
                    title = excluded.title,
                    scheduled_end_time = excluded.scheduled_end_time,
                    source_url = excluded.source_url,
                    updated_at = excluded.updated_at
                """,
                (
                    session.session_id,
                    session.session_type.value,
                    session.title,
                    self.dt_to_iso(session.scheduled_end_time),
                    session.source_url,
                    self.dt_to_iso(session.discovered_at),
                    self.dt_to_iso(session.updated_at),
                ),
            )

    def get_by_id(self, session_id: str) -> AuctionSession | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM auction_session WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return AuctionSession(
            session_id=row["session_id"],
            session_type=SessionType(row["session_type"]),
            title=row["title"],
            scheduled_end_time=self.iso_to_dt(row["scheduled_end_time"]),
            source_url=row["source_url"],
            discovered_at=self.iso_to_dt(row["discovered_at"]),  # type: ignore[arg-type]
            updated_at=self.iso_to_dt(row["updated_at"]),  # type: ignore[arg-type]
        )

    def list_recent(self, limit: int = 100) -> list[AuctionSession]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM auction_session ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            AuctionSession(
                session_id=row["session_id"],
                session_type=SessionType(row["session_type"]),
                title=row["title"],
                scheduled_end_time=self.iso_to_dt(row["scheduled_end_time"]),
                source_url=row["source_url"],
                discovered_at=self.iso_to_dt(row["discovered_at"]),  # type: ignore[arg-type]
                updated_at=self.iso_to_dt(row["updated_at"]),  # type: ignore[arg-type]
            )
            for row in rows
        ]

    @staticmethod
    def new(session_id: str, session_type, title: str, source_url: str) -> AuctionSession:
        # 发现阶段快速创建 Session 对象的便捷方法。
        now = datetime.now(timezone.utc)
        return AuctionSession(
            session_id=session_id,
            session_type=session_type,
            title=title,
            scheduled_end_time=None,
            source_url=source_url,
            discovered_at=now,
            updated_at=now,
        )
