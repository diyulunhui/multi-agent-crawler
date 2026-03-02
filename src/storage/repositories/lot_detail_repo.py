from __future__ import annotations

from src.domain.models import LotDetail
from src.storage.repositories.base_repo import BaseRepository


class LotDetailRepository(BaseRepository):
    def upsert_detail(self, detail: LotDetail) -> None:
        # 详情按 lot_id 幂等覆盖，保证重复抓取时保留最新版本。
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO lot_detail (
                    lot_id, title_raw, description_raw, current_price, start_price, end_time,
                    status, bid_count, look_count, fee_rate, winner, bid_history_html,
                    image_primary, images_json, video_url, labels_json, raw_json, fetched_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lot_id) DO UPDATE SET
                    title_raw = excluded.title_raw,
                    description_raw = excluded.description_raw,
                    current_price = excluded.current_price,
                    start_price = excluded.start_price,
                    end_time = excluded.end_time,
                    status = excluded.status,
                    bid_count = excluded.bid_count,
                    look_count = excluded.look_count,
                    fee_rate = excluded.fee_rate,
                    winner = excluded.winner,
                    bid_history_html = excluded.bid_history_html,
                    image_primary = excluded.image_primary,
                    images_json = excluded.images_json,
                    video_url = excluded.video_url,
                    labels_json = excluded.labels_json,
                    raw_json = excluded.raw_json,
                    fetched_at = excluded.fetched_at,
                    updated_at = excluded.updated_at
                """,
                (
                    detail.lot_id,
                    detail.title_raw,
                    detail.description_raw,
                    self.decimal_to_db(detail.current_price),
                    self.decimal_to_db(detail.start_price),
                    self.dt_to_iso(detail.end_time),
                    detail.status,
                    detail.bid_count,
                    detail.look_count,
                    self.decimal_to_db(detail.fee_rate),
                    detail.winner,
                    detail.bid_history_html,
                    detail.image_primary,
                    detail.images_json,
                    detail.video_url,
                    detail.labels_json,
                    detail.raw_json,
                    self.dt_to_iso(detail.fetched_at),
                    self.dt_to_iso(detail.updated_at),
                ),
            )

    def get_by_lot_id(self, lot_id: str) -> LotDetail | None:
        # 按拍品编号读取详情。
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lot_detail WHERE lot_id = ?", (lot_id,)).fetchone()
        if row is None:
            return None
        return LotDetail(
            lot_id=row["lot_id"],
            title_raw=row["title_raw"],
            description_raw=row["description_raw"],
            current_price=self.db_to_decimal(row["current_price"]),
            start_price=self.db_to_decimal(row["start_price"]),
            end_time=self.iso_to_dt(row["end_time"]),
            status=row["status"],
            bid_count=row["bid_count"],
            look_count=row["look_count"],
            fee_rate=self.db_to_decimal(row["fee_rate"]),
            winner=row["winner"],
            bid_history_html=row["bid_history_html"],
            image_primary=row["image_primary"],
            images_json=row["images_json"],
            video_url=row["video_url"],
            labels_json=row["labels_json"],
            raw_json=row["raw_json"],
            fetched_at=self.iso_to_dt(row["fetched_at"]),  # type: ignore[arg-type]
            updated_at=self.iso_to_dt(row["updated_at"]),  # type: ignore[arg-type]
        )
