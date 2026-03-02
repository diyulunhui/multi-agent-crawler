from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许从项目根目录直接运行该脚本，确保能导入 src 包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3

from src.scraping.url_guard import is_hx_allowed_url


def parse_args() -> argparse.Namespace:
    # 清洗参数：默认仅预览，传 --apply 才会实际删除。
    parser = argparse.ArgumentParser(description="清理 hx_auction.db 中的脏数据")
    parser.add_argument("--db", default="data/hx_auction.db", help="SQLite 数据库路径")
    parser.add_argument("--apply", action="store_true", help="执行删除；不传时仅预览")
    return parser.parse_args()


def _connect(db_path: Path) -> sqlite3.Connection:
    # 建立数据库连接并启用字典行访问。
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _load_dirty_session_ids(conn: sqlite3.Connection) -> list[str]:
    # 识别非华夏域名的专场记录。
    rows = conn.execute("SELECT session_id, source_url FROM auction_session").fetchall()
    return [row["session_id"] for row in rows if not is_hx_allowed_url(row["source_url"])]


def _load_dirty_lot_ids(conn: sqlite3.Connection, dirty_session_ids: list[str]) -> list[str]:
    # 识别脏专场下的 lot，以及孤儿 lot（session 不存在）。
    dirty_lot_ids: set[str] = set()
    if dirty_session_ids:
        placeholders = ",".join("?" for _ in dirty_session_ids)
        rows = conn.execute(
            f"SELECT lot_id FROM lot WHERE session_id IN ({placeholders})",
            tuple(dirty_session_ids),
        ).fetchall()
        dirty_lot_ids.update(str(row["lot_id"]) for row in rows)

    orphan_rows = conn.execute(
        """
        SELECT l.lot_id
        FROM lot l
        LEFT JOIN auction_session s ON s.session_id = l.session_id
        WHERE s.session_id IS NULL
        """
    ).fetchall()
    dirty_lot_ids.update(str(row["lot_id"]) for row in orphan_rows)
    return sorted(dirty_lot_ids)


def _count_table(conn: sqlite3.Connection, table_name: str) -> int:
    # 读取表行数，用于输出清洗前后对比。
    if not _table_exists(conn, table_name):
        return 0
    return int(conn.execute(f"SELECT COUNT(1) AS c FROM {table_name}").fetchone()["c"])


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    # 判断表是否存在，兼容旧库缺少新表的场景。
    row = conn.execute(
        "SELECT COUNT(1) AS c FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return int(row["c"]) > 0


def _delete_by_ids(conn: sqlite3.Connection, table: str, id_column: str, ids: list[str]) -> int:
    # 按主键列表删除数据，返回受影响行数。
    if not ids:
        return 0
    if not _table_exists(conn, table):
        return 0
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(f"DELETE FROM {table} WHERE {id_column} IN ({placeholders})", tuple(ids))
    return int(cur.rowcount if cur.rowcount is not None else 0)


def _delete_tasks_by_entity_ids(conn: sqlite3.Connection, entity_ids: list[str]) -> int:
    # 删除指向脏 session/lot 的任务状态，避免恢复任务再次污染数据。
    if not entity_ids:
        return 0
    if not _table_exists(conn, "task_state"):
        return 0
    placeholders = ",".join("?" for _ in entity_ids)
    cur = conn.execute(f"DELETE FROM task_state WHERE entity_id IN ({placeholders})", tuple(entity_ids))
    return int(cur.rowcount if cur.rowcount is not None else 0)


def main() -> None:
    # 执行预览或实删流程。
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    with _connect(db_path) as conn:
        before_counts = {
            name: _count_table(conn, name)
            for name in (
                "auction_session",
                "lot",
                "lot_detail",
                "lot_classification",
                "lot_structured",
                "review_queue",
                "lot_snapshot",
                "lot_result",
                "task_state",
            )
        }
        dirty_session_ids = _load_dirty_session_ids(conn)
        dirty_lot_ids = _load_dirty_lot_ids(conn, dirty_session_ids)

        # 孤儿详情/快照/结果也视为脏数据。
        orphan_detail_rows = conn.execute(
            "SELECT d.lot_id FROM lot_detail d LEFT JOIN lot l ON l.lot_id=d.lot_id WHERE l.lot_id IS NULL"
        ).fetchall()
        orphan_snapshot_rows = conn.execute(
            "SELECT s.lot_id FROM lot_snapshot s LEFT JOIN lot l ON l.lot_id=s.lot_id WHERE l.lot_id IS NULL"
        ).fetchall()
        orphan_result_rows = conn.execute(
            "SELECT r.lot_id FROM lot_result r LEFT JOIN lot l ON l.lot_id=r.lot_id WHERE l.lot_id IS NULL"
        ).fetchall()
        orphan_class_rows = (
            conn.execute(
                "SELECT c.lot_id FROM lot_classification c LEFT JOIN lot l ON l.lot_id=c.lot_id WHERE l.lot_id IS NULL"
            ).fetchall()
            if _table_exists(conn, "lot_classification")
            else []
        )
        orphan_structured_rows = (
            conn.execute(
                "SELECT s.lot_id FROM lot_structured s LEFT JOIN lot l ON l.lot_id=s.lot_id WHERE l.lot_id IS NULL"
            ).fetchall()
            if _table_exists(conn, "lot_structured")
            else []
        )

        orphan_lot_ids = sorted(
            set(
                str(row["lot_id"])
                for row in (
                    orphan_detail_rows
                    + orphan_snapshot_rows
                    + orphan_result_rows
                    + orphan_class_rows
                    + orphan_structured_rows
                )
            )
        )

        print("清洗预览:")
        print(f"- 脏 session 数量: {len(dirty_session_ids)}")
        print(f"- 脏 lot 数量: {len(dirty_lot_ids)}")
        print(f"- 孤儿详情/快照/结果 lot 数量: {len(orphan_lot_ids)}")
        if dirty_session_ids:
            print(f"- 脏 session 示例: {dirty_session_ids[:10]}")
        if dirty_lot_ids:
            print(f"- 脏 lot 示例: {dirty_lot_ids[:10]}")

        if not args.apply:
            print("当前为预览模式，未执行删除。传 --apply 可正式清洗。")
            return

        all_dirty_lot_ids = sorted(set(dirty_lot_ids + orphan_lot_ids))
        all_dirty_entity_ids = sorted(set(dirty_session_ids + all_dirty_lot_ids))

        deleted_task = _delete_tasks_by_entity_ids(conn, all_dirty_entity_ids)
        deleted_snap = _delete_by_ids(conn, "lot_snapshot", "lot_id", all_dirty_lot_ids)
        deleted_result = _delete_by_ids(conn, "lot_result", "lot_id", all_dirty_lot_ids)
        deleted_detail = _delete_by_ids(conn, "lot_detail", "lot_id", all_dirty_lot_ids)
        deleted_classification = _delete_by_ids(conn, "lot_classification", "lot_id", all_dirty_lot_ids)
        deleted_structured = _delete_by_ids(conn, "lot_structured", "lot_id", all_dirty_lot_ids)
        # review_queue 的 entity_id 对应 lot/session，统一按脏实体删除。
        deleted_review = _delete_by_ids(conn, "review_queue", "entity_id", all_dirty_entity_ids)
        deleted_lot = _delete_by_ids(conn, "lot", "lot_id", all_dirty_lot_ids)
        deleted_session = _delete_by_ids(conn, "auction_session", "session_id", dirty_session_ids)
        conn.commit()

        after_counts = {
            name: _count_table(conn, name)
            for name in (
                "auction_session",
                "lot",
                "lot_detail",
                "lot_classification",
                "lot_structured",
                "review_queue",
                "lot_snapshot",
                "lot_result",
                "task_state",
            )
        }

    print("清洗完成:")
    print(
        f"- 删除 session={deleted_session}, lot={deleted_lot}, detail={deleted_detail}, classification={deleted_classification}, "
        f"structured={deleted_structured}, review={deleted_review}, snapshot={deleted_snap}, result={deleted_result}, task={deleted_task}"
    )
    print("- 表行数变化:")
    for table_name in before_counts:
        print(f"  {table_name}: {before_counts[table_name]} -> {after_counts[table_name]}")


if __name__ == "__main__":
    main()
