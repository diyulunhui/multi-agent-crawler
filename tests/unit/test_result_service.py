from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.config.settings import AppConfig
from src.domain.events import SessionType
from src.domain.models import AuctionSession
from src.services.result_service import ResultService
from src.storage.db import Database
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.session_repo import SessionRepository


class ResultServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        cfg = AppConfig.from_env()
        self.config = replace(cfg, db_url="sqlite:///data/test_result_service.db")

        db_path = Path("data/test_result_service.db")
        if db_path.exists():
            db_path.unlink()

        self.db = Database(self.config)
        self.db.init_schema()

        now = datetime.now(timezone.utc)
        SessionRepository(self.db).upsert_session(
            AuctionSession(
                session_id="s_result",
                session_type=SessionType.SPECIAL,
                title="result session",
                scheduled_end_time=now,
                source_url="https://example.com/session",
                discovered_at=now,
                updated_at=now,
            )
        )
        LotRepository(self.db).upsert_lot(LotRepository(self.db).new("l_result", "s_result", "lot", now))
        self.service = ResultService(self.db)

    def test_null_price_should_not_override_confirmed_price(self) -> None:
        ended_at = datetime(2026, 3, 2, 1, 0, tzinfo=timezone.utc)
        self.service.upsert_from_snapshot(
            lot_id="l_result",
            final_price=Decimal("100.0"),
            final_end_time=ended_at,
            confidence_score=Decimal("0.95"),
            decided_from_snapshot="FINAL",
            is_unsold=False,
            is_withdrawn=False,
        )
        self.service.upsert_from_snapshot(
            lot_id="l_result",
            final_price=None,
            final_end_time=None,
            confidence_score=Decimal("0.70"),
            decided_from_snapshot="FINAL",
            is_unsold=False,
            is_withdrawn=False,
        )

        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lot_result WHERE lot_id = 'l_result'").fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(100.0, row["final_price"])
        self.assertEqual(ended_at.isoformat(), row["final_end_time"])
        self.assertEqual(0.95, row["confidence_score"])
        self.assertEqual(0, row["is_unsold"])
        self.assertEqual(0, row["is_withdrawn"])

    def test_terminal_unsold_with_higher_confidence_can_clear_price(self) -> None:
        self.service.upsert_from_snapshot(
            lot_id="l_result",
            final_price=Decimal("88.0"),
            final_end_time=None,
            confidence_score=Decimal("0.70"),
            decided_from_snapshot="FINAL",
            is_unsold=False,
            is_withdrawn=False,
        )
        self.service.upsert_from_snapshot(
            lot_id="l_result",
            final_price=None,
            final_end_time=None,
            confidence_score=Decimal("0.92"),
            decided_from_snapshot="FINAL",
            is_unsold=True,
            is_withdrawn=False,
        )

        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lot_result WHERE lot_id = 'l_result'").fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertIsNone(row["final_price"])
        self.assertEqual(1, row["is_unsold"])
        self.assertEqual(0, row["is_withdrawn"])
        self.assertEqual(0.92, row["confidence_score"])

    def test_higher_confidence_price_should_replace_unsold_state(self) -> None:
        self.service.upsert_from_snapshot(
            lot_id="l_result",
            final_price=None,
            final_end_time=None,
            confidence_score=Decimal("0.75"),
            decided_from_snapshot="FINAL",
            is_unsold=True,
            is_withdrawn=False,
        )
        ended_at = datetime(2026, 3, 2, 2, 0, tzinfo=timezone.utc)
        self.service.upsert_from_snapshot(
            lot_id="l_result",
            final_price=Decimal("120.0"),
            final_end_time=ended_at,
            confidence_score=Decimal("0.93"),
            decided_from_snapshot="FINAL",
            is_unsold=False,
            is_withdrawn=False,
        )

        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM lot_result WHERE lot_id = 'l_result'").fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(120.0, row["final_price"])
        self.assertEqual(ended_at.isoformat(), row["final_end_time"])
        self.assertEqual(0, row["is_unsold"])
        self.assertEqual(0, row["is_withdrawn"])
        self.assertEqual(0.93, row["confidence_score"])


if __name__ == "__main__":
    unittest.main()
