from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.config.settings import AppConfig
from src.domain.events import SessionType
from src.domain.models import AuctionSession, Lot, LotStructured
from src.storage.db import Database
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.lot_structured_repo import LotStructuredRepository
from src.storage.repositories.session_repo import SessionRepository


class LotStructuredRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例使用独立数据库，防止相互污染。
        cfg = AppConfig.from_env()
        self.config = replace(cfg, db_url="sqlite:///data/test_lot_structured.db")

        db_path = Path("data/test_lot_structured.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()

        now = datetime.now(timezone.utc)
        SessionRepository(self.db).upsert_session(
            AuctionSession(
                session_id="s_struct",
                session_type=SessionType.SPECIAL,
                title="结构化专场",
                scheduled_end_time=now,
                source_url="https://www.hxguquan.com/goods-list.html?gid=1",
                discovered_at=now,
                updated_at=now,
            )
        )
        LotRepository(self.db).upsert_lot(
            Lot(
                lot_id="l_struct",
                session_id="s_struct",
                title_raw="PCGS MS64 袁大头",
                description_raw="描述",
                category="机制币",
                grade_agency=None,
                grade_score=None,
                end_time=now,
                status="bidding",
                last_seen_at=now,
                updated_at=now,
            )
        )

    def test_upsert_and_get_structured(self) -> None:
        # 写入结构化结果并读取，验证关键字段完整保存。
        repo = LotStructuredRepository(self.db)
        now = datetime.now(timezone.utc)
        repo.upsert_structured(
            LotStructured(
                lot_id="l_struct",
                coin_type="机制币",
                variety="袁大头",
                mint_year="三年",
                grading_company="PCGS",
                grade_score="MS64",
                denomination="壹圆",
                special_tags_json='["原味包浆"]',
                confidence_score=Decimal("0.91"),
                extract_source="title_rules",
                schema_version="structured-rule-v1",
                raw_structured_json='{"lot_id":"l_struct"}',
                updated_at=now,
            )
        )

        saved = repo.get_by_lot_id("l_struct")
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual("机制币", saved.coin_type)
        self.assertEqual("PCGS", saved.grading_company)
        self.assertEqual(Decimal("0.91"), saved.confidence_score)

    def test_schema_contains_lot_structured_table(self) -> None:
        # 确认 schema 已创建 lot_structured 表，避免老逻辑漏建表。
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(1) AS c FROM sqlite_master WHERE type='table' AND name='lot_structured'"
            ).fetchone()
        self.assertEqual(1, row["c"])


if __name__ == "__main__":
    unittest.main()
