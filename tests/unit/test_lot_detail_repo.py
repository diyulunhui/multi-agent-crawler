from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.config.settings import AppConfig
from src.domain.events import SessionType
from src.domain.models import AuctionSession, Lot, LotDetail
from src.storage.db import Database
from src.storage.repositories.lot_detail_repo import LotDetailRepository
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.session_repo import SessionRepository


class LotDetailRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 准备独立测试数据库，避免污染运行数据。
        cfg = AppConfig.from_env()
        self.config = replace(cfg, db_url="sqlite:///data/test_lot_detail.db")

        db_path = Path("data/test_lot_detail.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()

        now = datetime.now(timezone.utc)
        SessionRepository(self.db).upsert_session(
            AuctionSession(
                session_id="s_detail",
                session_type=SessionType.SPECIAL,
                title="detail session",
                scheduled_end_time=now,
                source_url="https://example.com/session",
                discovered_at=now,
                updated_at=now,
            )
        )
        LotRepository(self.db).upsert_lot(
            Lot(
                lot_id="l_detail",
                session_id="s_detail",
                title_raw="lot title",
                description_raw="lot desc",
                category="coin",
                grade_agency="PCGS",
                grade_score="MS64",
                end_time=now,
                status="bidding",
                last_seen_at=now,
                updated_at=now,
            )
        )

    def test_upsert_and_get_detail(self) -> None:
        # 写入详情并读取，验证关键字段保持一致。
        repo = LotDetailRepository(self.db)
        now = datetime.now(timezone.utc)
        repo.upsert_detail(
            LotDetail(
                lot_id="l_detail",
                title_raw="lot title detail",
                description_raw="完整描述",
                current_price=Decimal("1234"),
                start_price=Decimal("1000"),
                end_time=now,
                status="bidding",
                bid_count=6,
                look_count=18,
                fee_rate=Decimal("4.5"),
                winner=None,
                bid_history_html="<ul><li>bid</li></ul>",
                image_primary="https://imgali.huaxiaguquan.com/pic/a.jpg",
                images_json='["https://imgali.huaxiaguquan.com/pic/a.jpg"]',
                video_url="https://imgali.huaxiaguquan.com/video/a.mp4",
                labels_json='["机制币"]',
                raw_json='{"itemcode":"l_detail","itemname":"lot title detail"}',
                fetched_at=now,
                updated_at=now,
            )
        )
        detail = repo.get_by_lot_id("l_detail")
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual("完整描述", detail.description_raw)
        self.assertEqual(Decimal("1234"), detail.current_price)
        self.assertEqual(Decimal("4.5"), detail.fee_rate)
        self.assertIn("itemname", detail.raw_json)

    def test_schema_contains_description_column(self) -> None:
        # 确认 lot 表已包含 description_raw 列，避免老库读取失败。
        with self.db.connection() as conn:
            names = [row["name"] for row in conn.execute("PRAGMA table_info(lot)").fetchall()]
        self.assertIn("description_raw", names)


if __name__ == "__main__":
    unittest.main()
