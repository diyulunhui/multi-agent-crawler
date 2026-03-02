from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.config.settings import AppConfig


def _db_path_from_url(db_url: str) -> Path:
    # 当前实现仅支持 sqlite:/// 本地文件连接串。
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        raise ValueError(f"Only sqlite db_url is supported, got: {db_url}")
    return Path(db_url[len(prefix) :])


class Database:
    def __init__(self, config: AppConfig, schema_path: str = "src/storage/schema.sql") -> None:
        self._config = config
        self._db_path = _db_path_from_url(config.db_url)
        self._schema_path = Path(schema_path)

    def ensure_parent_dir(self) -> None:
        # 确保数据库目录存在，避免首次启动失败。
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # 统一连接生命周期，自动提交/回滚事务。
        self.ensure_parent_dir()
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        # 启动时初始化（或修复）表结构。
        sql = self._schema_path.read_text(encoding="utf-8")
        with self.connection() as conn:
            conn.executescript(sql)
            # 兼容历史库：旧 lot 表没有 description_raw 列时自动补齐。
            self._ensure_column(conn, table_name="lot", column_name="description_raw", column_type="TEXT")
            # 兼容历史库：旧 task_state 没有 payload_json 时补齐。
            self._ensure_column(
                conn,
                table_name="task_state",
                column_name="payload_json",
                column_type="TEXT DEFAULT '{}'",
            )
            # 兼容历史库：补齐历史任务缺失 payload，避免恢复后执行器缺参失败。
            self._backfill_task_payload(conn)

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
        # 查询表字段，判断指定列是否已存在。
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(str(row["name"]) == column_name for row in rows)

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        # 缺列时执行轻量迁移，保证老数据可继续被新代码读取。
        if self._has_column(conn, table_name=table_name, column_name=column_name):
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def _backfill_task_payload(self, conn: sqlite3.Connection) -> None:
        # 历史库升级后，task_state 可能存在 payload_json 为空的任务。
        rows = conn.execute(
            """
            SELECT task_id, event_type, entity_id
            FROM task_state
            WHERE payload_json IS NULL OR TRIM(payload_json) = '' OR TRIM(payload_json) = '{}'
            """
        ).fetchall()

        if not rows:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        snapshot_events = {"SNAPSHOT_PRE5", "SNAPSHOT_PRE1", "SNAPSHOT_FINAL_MONITOR"}
        for row in rows:
            task_id = str(row["task_id"])
            event_type = str(row["event_type"])
            entity_id = str(row["entity_id"])
            payload: dict | None = None

            if event_type in snapshot_events:
                lot_row = conn.execute(
                    """
                    SELECT l.lot_id, l.session_id, s.source_url
                    FROM lot l
                    JOIN auction_session s ON s.session_id = l.session_id
                    WHERE l.lot_id = ?
                    LIMIT 1
                    """,
                    (entity_id,),
                ).fetchone()
                if lot_row is not None:
                    payload = {
                        "lot_id": str(lot_row["lot_id"]),
                        "session_id": str(lot_row["session_id"]),
                        "url": str(lot_row["source_url"]),
                    }
            elif event_type == "SESSION_FINAL_SCRAPE":
                session_row = conn.execute(
                    "SELECT session_id, source_url FROM auction_session WHERE session_id = ? LIMIT 1",
                    (entity_id,),
                ).fetchone()
                if session_row is not None:
                    payload = {"url": str(session_row["source_url"])}
            elif event_type == "DISCOVER_LOTS":
                session_row = conn.execute(
                    "SELECT session_id, source_url FROM auction_session WHERE session_id = ? LIMIT 1",
                    (entity_id,),
                ).fetchone()
                if session_row is not None:
                    payload = {
                        "session_id": str(session_row["session_id"]),
                        "url": str(session_row["source_url"]),
                    }
            elif event_type == "DISCOVER_SESSIONS":
                payload = {"site": self._config.site_name, "url": "https://www.hxguquan.com/"}

            if payload is None:
                continue

            conn.execute(
                """
                UPDATE task_state
                SET payload_json = ?, status = 'pending', retry_count = 0, last_error = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), now_iso, task_id),
            )

        # 历史上因缺参进入 failed/dead 的任务，在 payload 修复后统一恢复执行。
        conn.execute(
            """
            UPDATE task_state
            SET status = 'pending', retry_count = 0, last_error = NULL, updated_at = ?
            WHERE status IN ('failed', 'dead')
              AND (
                  last_error LIKE '%缺少 url/lot_id/session_id%'
                  OR (event_type = 'DISCOVER_SESSIONS' AND last_error LIKE 'unknown url type:%')
              )
              AND payload_json IS NOT NULL
              AND TRIM(payload_json) <> ''
              AND TRIM(payload_json) <> '{}'
            """,
            (now_iso,),
        )
