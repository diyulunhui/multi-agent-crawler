from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from src.config.settings import AppConfig
from src.domain.events import SnapshotType
from src.storage.db import Database
from src.storage.object_store import LocalObjectStore


class SnapshotService:
    def __init__(self, config: AppConfig, db: Database, object_store: LocalObjectStore) -> None:
        self.config = config
        self.db = db
        self.object_store = object_store

    def save_from_parsed(
        self,
        lot_id: str,
        snapshot_type: SnapshotType,
        current_price: Decimal | None,
        bid_count: int | None,
        raw_html: str,
        snapshot_time: datetime,
        session_id: str,
        quality_score: Decimal = Decimal("1.0"),
    ) -> str:
        # 快照按分钟桶幂等，避免重复写入脏数据。
        bucket = snapshot_time.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        idempotency_key = f"{lot_id}:{snapshot_type.value}:{bucket}"

        raw_ref = self.object_store.save_html(
            site=self.config.site_name,
            snapshot_time=snapshot_time,
            session_id=session_id,
            lot_id=lot_id,
            snapshot_type=snapshot_type.value,
            html=raw_html,
        )

        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO lot_snapshot (
                    snapshot_id, lot_id, snapshot_time, snapshot_type,
                    current_price, bid_count, raw_ref, quality_score, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    current_price = excluded.current_price,
                    bid_count = excluded.bid_count,
                    raw_ref = excluded.raw_ref,
                    quality_score = excluded.quality_score,
                    snapshot_time = excluded.snapshot_time
                """,
                (
                    f"snap_{uuid4().hex}",
                    lot_id,
                    snapshot_time.astimezone(timezone.utc).isoformat(),
                    snapshot_type.value,
                    float(current_price) if current_price is not None else None,
                    bid_count,
                    raw_ref,
                    float(quality_score),
                    idempotency_key,
                ),
            )

        return raw_ref
