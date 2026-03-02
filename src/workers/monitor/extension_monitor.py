from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from src.scraping.adapter import ScraplingAdapter
from src.scraping.parsers.hx_parser import ParsedLot


@dataclass
class MonitorOutcome:
    # 顺延监控结果。
    lot: ParsedLot | None
    closed: bool
    timed_out: bool
    polls: int


class ExtensionMonitor:
    def __init__(
        self,
        adapter: ScraplingAdapter,
        poll_seconds: int,
        max_minutes: int,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adapter = adapter
        self.poll_seconds = poll_seconds
        self.max_minutes = max_minutes
        self.sleep_fn = sleep_fn

    def monitor(self, url: str, lot_id: str, session_id: str) -> MonitorOutcome:
        # 低频轮询直到 closed 或超时。
        deadline = datetime.now(timezone.utc) + timedelta(minutes=self.max_minutes)
        polls = 0
        last_lot: ParsedLot | None = None

        while datetime.now(timezone.utc) < deadline:
            raw = self.adapter.fetch_page(url)
            lots = self.adapter.parse_lots(raw)
            polls += 1

            target = self._find_target(lots, lot_id, session_id)
            if target is not None:
                last_lot = target
                if target.status == "closed":
                    return MonitorOutcome(lot=target, closed=True, timed_out=False, polls=polls)

            self.sleep_fn(float(self.poll_seconds))

        return MonitorOutcome(lot=last_lot, closed=False, timed_out=True, polls=polls)

    @staticmethod
    def _find_target(lots: list[ParsedLot], lot_id: str, session_id: str) -> ParsedLot | None:
        for lot in lots:
            if lot.lot_id == lot_id and lot.session_id == session_id:
                return lot
        return None
