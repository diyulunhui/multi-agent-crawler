from __future__ import annotations

import argparse
import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def _connect(db_path: Path) -> sqlite3.Connection:
    # 每次请求创建独立连接，避免多线程共享连接带来的并发问题。
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _coerce_limit(raw_value: str | None, default_value: int, max_value: int) -> int:
    # 对外部参数做上限保护，防止一次性拉取过多数据。
    if raw_value is None:
        return default_value
    try:
        parsed = int(raw_value)
    except ValueError:
        return default_value
    return max(1, min(parsed, max_value))


def _query_sessions(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    # 查询最近更新的专场，供前端筛选。
    rows = conn.execute(
        """
        SELECT session_id, session_type, title, scheduled_end_time, source_url, updated_at
        FROM auction_session
        WHERE source_url LIKE '%hxguquan.com%' OR source_url LIKE '%huaxiaguquan.com%'
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [{k: row[k] for k in row.keys()} for row in rows]


def _query_lots(
    conn: sqlite3.Connection,
    session_id: str | None,
    keyword: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    # 查询列表页数据，优先展示详情表中的描述与价格信息。
    sql = """
    SELECT
        l.lot_id,
        l.session_id,
        s.title AS session_title,
        l.title_raw,
        COALESCE(ld.description_raw, l.description_raw) AS description_raw,
        COALESCE(c.category_l1, l.category) AS category,
        c.category_l2 AS category_l2,
        l.grade_agency,
        l.grade_score,
        l.end_time,
        l.status,
        l.updated_at,
        ld.current_price AS detail_current_price,
        ld.bid_count AS detail_bid_count,
        ld.video_url,
        ld.image_primary,
        r.final_price,
        r.final_end_time
    FROM lot l
    LEFT JOIN auction_session s ON s.session_id = l.session_id
    LEFT JOIN lot_detail ld ON ld.lot_id = l.lot_id
    LEFT JOIN lot_classification c ON c.lot_id = l.lot_id
    LEFT JOIN lot_result r ON r.lot_id = l.lot_id
    WHERE 1 = 1
      AND (s.source_url LIKE '%hxguquan.com%' OR s.source_url LIKE '%huaxiaguquan.com%')
    """
    params: list[Any] = []
    if session_id:
        sql += " AND l.session_id = ?"
        params.append(session_id)
    if keyword:
        like = f"%{keyword}%"
        sql += " AND (l.lot_id LIKE ? OR l.title_raw LIKE ? OR COALESCE(ld.description_raw, l.description_raw, '') LIKE ?)"
        params.extend([like, like, like])
    sql += " ORDER BY COALESCE(l.end_time, '9999-12-31T23:59:59') ASC, l.updated_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, tuple(params)).fetchall()
    return [{k: row[k] for k in row.keys()} for row in rows]


def _query_lot_detail(conn: sqlite3.Connection, lot_id: str) -> dict[str, Any] | None:
    # 查询单个拍品详情，并把 JSON 字段转换为可直接渲染的对象。
    row = conn.execute(
        """
        SELECT
            l.lot_id,
            l.session_id,
            l.title_raw AS list_title_raw,
            l.description_raw AS list_description_raw,
            l.status AS list_status,
            l.end_time AS list_end_time,
            c.category_l1,
            c.category_l2,
            c.rule_hit,
            c.confidence_score,
            ld.title_raw AS detail_title_raw,
            ld.description_raw AS detail_description_raw,
            ld.current_price,
            ld.start_price,
            ld.end_time,
            ld.status,
            ld.bid_count,
            ld.look_count,
            ld.fee_rate,
            ld.winner,
            ld.bid_history_html,
            ld.image_primary,
            ld.images_json,
            ld.video_url,
            ld.labels_json,
            ld.raw_json,
            ld.fetched_at,
            ld.updated_at
        FROM lot l
        LEFT JOIN lot_classification c ON c.lot_id = l.lot_id
        LEFT JOIN lot_detail ld ON ld.lot_id = l.lot_id
        WHERE l.lot_id = ?
        """,
        (lot_id,),
    ).fetchone()
    if row is None:
        return None

    data = {k: row[k] for k in row.keys()}
    # 解析 JSON 文本字段，前端不再重复做 try/catch。
    data["images"] = _parse_json_text(data.get("images_json"))
    data["labels"] = _parse_json_text(data.get("labels_json"))
    data["raw"] = _parse_json_text(data.get("raw_json"))
    return data


def _parse_json_text(value: Any) -> Any:
    # 容错解析 JSON 文本，失败时返回 None。
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


class LotViewerHandler(BaseHTTPRequestHandler):
    # 通过类变量注入数据库路径，便于复用同一个 Handler 类型。
    db_path: Path = Path("data/hx_auction.db")

    def do_GET(self) -> None:  # noqa: N802
        # 根据路径分发页面与 API。
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(self._build_page())
            return
        if parsed.path == "/api/sessions":
            self._handle_sessions(parsed.query)
            return
        if parsed.path == "/api/lots":
            self._handle_lots(parsed.query)
            return
        if parsed.path == "/api/lot-detail":
            self._handle_lot_detail(parsed.query)
            return
        self._send_text_error(HTTPStatus.NOT_FOUND, "not found")

    def _handle_sessions(self, query_string: str) -> None:
        # 返回专场列表。
        query = parse_qs(query_string)
        limit = _coerce_limit(query.get("limit", [None])[0], default_value=200, max_value=1000)
        with _connect(self.db_path) as conn:
            payload = {"sessions": _query_sessions(conn, limit)}
        self._send_json(payload)

    def _handle_lots(self, query_string: str) -> None:
        # 返回拍品列表。
        query = parse_qs(query_string)
        session_id = (query.get("session_id", [""])[0] or "").strip() or None
        keyword = (query.get("q", [""])[0] or "").strip() or None
        limit = _coerce_limit(query.get("limit", [None])[0], default_value=500, max_value=3000)
        with _connect(self.db_path) as conn:
            lots = _query_lots(conn, session_id=session_id, keyword=keyword, limit=limit)
        self._send_json({"count": len(lots), "lots": lots})

    def _handle_lot_detail(self, query_string: str) -> None:
        # 返回单个拍品的完整详情。
        query = parse_qs(query_string)
        lot_id = (query.get("lot_id", [""])[0] or "").strip()
        if not lot_id:
            self._send_text_error(HTTPStatus.BAD_REQUEST, "missing lot_id")
            return
        with _connect(self.db_path) as conn:
            detail = _query_lot_detail(conn, lot_id=lot_id)
        if detail is None:
            self._send_text_error(HTTPStatus.NOT_FOUND, "lot not found")
            return
        self._send_json(detail)

    def _send_text_error(self, status: HTTPStatus, message: str) -> None:
        # 用 UTF-8 文本返回错误，避免 BaseHTTPRequestHandler 的 latin-1 限制。
        body = message.encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any) -> None:
        # 统一 JSON 输出编码。
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        # 首页 HTML 输出。
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # 默认关闭访问日志，避免终端输出噪音过大。
        return

    @staticmethod
    def _build_page() -> str:
        # 页面内嵌脚本直接请求本机 API，方便单文件部署。
        return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>拍品详情查看</title>
  <style>
    :root {
      --bg: #f6f2e7;
      --card: #fffdf7;
      --line: #d8ccb6;
      --ink: #2f2617;
      --accent: #8f3f24;
      --muted: #7a6f60;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Noto Serif SC", "Songti SC", "PingFang SC", serif;
      background: radial-gradient(circle at top right, #f4e7d5 0%, var(--bg) 45%, #efe6d7 100%);
      color: var(--ink);
    }
    .wrap { padding: 16px; }
    .toolbar {
      display: grid;
      grid-template-columns: 1fr 1fr auto auto;
      gap: 8px;
      margin-bottom: 12px;
    }
    input, select, button {
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 10px;
      background: var(--card);
      color: var(--ink);
    }
    button {
      background: var(--accent);
      color: #fff;
      border: none;
      cursor: pointer;
    }
    .grid {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 12px;
    }
    .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      min-height: 480px;
      overflow: auto;
    }
    .row {
      border-bottom: 1px dashed var(--line);
      padding: 10px 0;
      cursor: pointer;
    }
    .row:last-child { border-bottom: none; }
    .row h4 { margin: 0 0 6px; font-size: 16px; }
    .meta { color: var(--muted); font-size: 13px; }
    .desc { color: var(--ink); font-size: 13px; margin-top: 6px; }
    .kv { margin-bottom: 8px; }
    .kv b { color: var(--accent); }
    .images {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .images img {
      width: 100%;
      height: 110px;
      object-fit: cover;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-all;
      background: #f8f4eb;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      font-size: 12px;
      margin-top: 8px;
    }
    .empty { color: var(--muted); }
    @media (max-width: 960px) {
      .toolbar { grid-template-columns: 1fr; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="toolbar">
      <select id="sessionSelect"></select>
      <input id="searchInput" placeholder="输入编号/标题/描述关键词" />
      <button id="reloadBtn">刷新列表</button>
      <button id="clearBtn">清空筛选</button>
    </div>
    <div class="grid">
      <div class="panel">
        <div id="listCount" class="meta"></div>
        <div id="lotList"></div>
      </div>
      <div class="panel" id="detailPanel">
        <div class="empty">点击左侧拍品后显示详情</div>
      </div>
    </div>
  </div>

  <script>
    const sessionSelect = document.getElementById("sessionSelect");
    const searchInput = document.getElementById("searchInput");
    const lotList = document.getElementById("lotList");
    const listCount = document.getElementById("listCount");
    const detailPanel = document.getElementById("detailPanel");
    const reloadBtn = document.getElementById("reloadBtn");
    const clearBtn = document.getElementById("clearBtn");

    async function loadSessions() {
      const res = await fetch("/api/sessions?limit=500");
      const data = await res.json();
      sessionSelect.innerHTML = '<option value="">全部专场</option>';
      for (const s of data.sessions) {
        const opt = document.createElement("option");
        opt.value = s.session_id;
        opt.textContent = `[${s.session_id}] ${s.title}`;
        sessionSelect.appendChild(opt);
      }
    }

    function escapeHtml(text) {
      if (text === null || text === undefined) return "";
      return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    async function loadLots() {
      const params = new URLSearchParams();
      if (sessionSelect.value) params.set("session_id", sessionSelect.value);
      if (searchInput.value.trim()) params.set("q", searchInput.value.trim());
      params.set("limit", "2000");

      const res = await fetch(`/api/lots?${params.toString()}`);
      const data = await res.json();

      listCount.textContent = `共 ${data.count} 条拍品`;
      lotList.innerHTML = "";
      if (!data.lots.length) {
        lotList.innerHTML = '<div class="empty">当前没有匹配拍品</div>';
        return;
      }

      for (const lot of data.lots) {
        const row = document.createElement("div");
        row.className = "row";
        row.innerHTML = `
          <h4>${escapeHtml(lot.title_raw)} <small class="meta">#${escapeHtml(lot.lot_id)}</small></h4>
          <div class="meta">专场：${escapeHtml(lot.session_title || lot.session_id)} | 状态：${escapeHtml(lot.status)} | 结标：${escapeHtml(lot.end_time || "")}</div>
          <div class="meta">分类：${escapeHtml(lot.category || "-")}${lot.category_l2 ? "/" + escapeHtml(lot.category_l2) : ""} | 当前价：${escapeHtml(lot.detail_current_price || "-")} | 最终价：${escapeHtml(lot.final_price || "-")}</div>
          <div class="desc">${escapeHtml(lot.description_raw || "").slice(0, 160)}</div>
        `;
        row.addEventListener("click", () => loadDetail(lot.lot_id));
        lotList.appendChild(row);
      }
    }

    async function loadDetail(lotId) {
      const res = await fetch(`/api/lot-detail?lot_id=${encodeURIComponent(lotId)}`);
      if (!res.ok) {
        detailPanel.innerHTML = '<div class="empty">详情加载失败</div>';
        return;
      }
      const detail = await res.json();
      const images = Array.isArray(detail.images) ? detail.images : [];
      const labels = Array.isArray(detail.labels) ? detail.labels.join(" / ") : "";
      const rawJsonText = detail.raw ? JSON.stringify(detail.raw, null, 2) : "";

      detailPanel.innerHTML = `
        <div class="kv"><b>抬头/标题：</b>${escapeHtml(detail.detail_title_raw || detail.list_title_raw || "")}</div>
        <div class="kv"><b>编号：</b>${escapeHtml(detail.lot_id || "")}</div>
        <div class="kv"><b>描述：</b>${escapeHtml(detail.detail_description_raw || detail.list_description_raw || "")}</div>
        <div class="kv"><b>状态：</b>${escapeHtml(detail.status || detail.list_status || "")}</div>
        <div class="kv"><b>分类：</b>${escapeHtml(detail.category_l1 || "")}${detail.category_l2 ? "/" + escapeHtml(detail.category_l2) : ""}</div>
        <div class="kv"><b>分类命中规则：</b>${escapeHtml(detail.rule_hit || "")}（置信度: ${escapeHtml(detail.confidence_score || "")}）</div>
        <div class="kv"><b>当前价：</b>${escapeHtml(detail.current_price || "")}</div>
        <div class="kv"><b>起拍价：</b>${escapeHtml(detail.start_price || "")}</div>
        <div class="kv"><b>出价次数：</b>${escapeHtml(detail.bid_count || "")}</div>
        <div class="kv"><b>围观人数：</b>${escapeHtml(detail.look_count || "")}</div>
        <div class="kv"><b>服务费率：</b>${escapeHtml(detail.fee_rate || "")}</div>
        <div class="kv"><b>结标时间：</b>${escapeHtml(detail.end_time || detail.list_end_time || "")}</div>
        <div class="kv"><b>赢家：</b>${escapeHtml(detail.winner || "")}</div>
        <div class="kv"><b>标签：</b>${escapeHtml(labels)}</div>
        <div class="kv"><b>主图：</b>${detail.image_primary ? `<a target="_blank" href="${escapeHtml(detail.image_primary)}">${escapeHtml(detail.image_primary)}</a>` : "-"}</div>
        <div class="kv"><b>视频：</b>${detail.video_url ? `<a target="_blank" href="${escapeHtml(detail.video_url)}">${escapeHtml(detail.video_url)}</a>` : "-"}</div>
        <div class="kv"><b>出价记录（原始 HTML）：</b></div>
        <pre>${escapeHtml(detail.bid_history_html || "")}</pre>
        <div class="kv"><b>图片列表：</b></div>
        <div class="images">${images.map(url => `<a target="_blank" href="${escapeHtml(url)}"><img src="${escapeHtml(url)}" /></a>`).join("")}</div>
        <div class="kv"><b>原始 JSON（全量字段）：</b></div>
        <pre>${escapeHtml(rawJsonText)}</pre>
      `;
    }

    reloadBtn.addEventListener("click", loadLots);
    clearBtn.addEventListener("click", () => {
      sessionSelect.value = "";
      searchInput.value = "";
      loadLots();
    });
    sessionSelect.addEventListener("change", loadLots);
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") loadLots();
    });

    (async () => {
      await loadSessions();
      await loadLots();
    })();
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    # 启动参数：数据库文件与监听地址。
    parser = argparse.ArgumentParser(description="拍品详情本地查看页面")
    parser.add_argument("--db", default="data/hx_auction.db", help="SQLite 数据库路径")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    return parser.parse_args()


def main() -> None:
    # 启动 HTTP 服务，提供页面和 JSON 接口。
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    LotViewerHandler.db_path = db_path
    server = ThreadingHTTPServer((args.host, args.port), LotViewerHandler)
    print(f"lot viewer running at http://{args.host}:{args.port} (db={db_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
