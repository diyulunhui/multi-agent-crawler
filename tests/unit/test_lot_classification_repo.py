from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.config.settings import AppConfig
from src.domain.events import SessionType
from src.domain.models import AuctionSession, Lot, LotClassification
from src.storage.db import Database
from src.storage.repositories.lot_classification_repo import LotClassificationRepository
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.session_repo import SessionRepository


class LotClassificationRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 使用独立测试库，避免污染运行环境。
        cfg = AppConfig.from_env()
        self.config = replace(cfg, db_url="sqlite:///data/test_lot_classification.db")

        db_path = Path("data/test_lot_classification.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()

        now = datetime.now(timezone.utc)
        SessionRepository(self.db).upsert_session(
            AuctionSession(
                session_id="s_cls",
                session_type=SessionType.SPECIAL,
                title="分类专场",
                scheduled_end_time=now,
                source_url="https://www.hxguquan.com/goods-list.html?gid=1",
                discovered_at=now,
                updated_at=now,
            )
        )
        LotRepository(self.db).upsert_lot(
            Lot(
                lot_id="l_cls",
                session_id="s_cls",
                title_raw="测试拍品",
                description_raw="测试描述",
                category=None,
                grade_agency=None,
                grade_score=None,
                end_time=now,
                status="bidding",
                last_seen_at=now,
                updated_at=now,
            )
        )

    def test_upsert_and_get_classification(self) -> None:
        # 验证分类结果可正确写入并读回。
        repo = LotClassificationRepository(self.db)
        now = datetime.now(timezone.utc)
        repo.upsert_classification(
            LotClassification(
                lot_id="l_cls",
                category_l1="机制币",
                category_l2="银币",
                tags_json='["机制币","银币"]',
                rule_hit="labels:机制币",
                confidence_score=Decimal("0.95"),
                classifier_version="rule-v1",
                updated_at=now,
            )
        )
        got = repo.get_by_lot_id("l_cls")
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual("机制币", got.category_l1)
        self.assertEqual("银币", got.category_l2)
        self.assertEqual(Decimal("0.95"), got.confidence_score)


if __name__ == "__main__":
    unittest.main()
