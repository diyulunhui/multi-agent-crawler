from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.storage.db import Database


class BaseRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def now_iso() -> str:
        # 仓储层统一使用 UTC ISO 时间格式。
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def dt_to_iso(value: datetime | None) -> str | None:
        # datetime -> ISO 文本，便于 SQLite 存储。
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def iso_to_dt(value: str | None) -> datetime | None:
        # ISO 文本 -> datetime。
        if value is None:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def decimal_to_db(value: Decimal | None) -> float | None:
        # Decimal -> float，适配 SQLite NUMERIC。
        if value is None:
            return None
        return float(value)

    @staticmethod
    def db_to_decimal(value: Any) -> Decimal | None:
        # 数据库数值 -> Decimal，避免精度误差扩散。
        if value is None:
            return None
        return Decimal(str(value))

    @staticmethod
    def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {k: row[k] for k in row.keys()}
