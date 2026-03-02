from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.scraping.normalizers import (
    clean_text,
    normalize_grade_agency,
    normalize_grade_score,
    normalize_status,
    parse_datetime,
    parse_decimal,
)


@dataclass
class ParsedSession:
    session_id: str
    session_type: str
    title: str
    source_url: str
    scheduled_end_time: str | None


@dataclass
class ParsedLot:
    lot_id: str
    session_id: str
    title_raw: str
    description_raw: str | None
    end_time: str | None
    status: str
    current_price: str | None
    bid_count: int | None
    category: str | None
    grade_agency: str | None
    grade_score: str | None


@dataclass
class ParsedLotDetail:
    # 详情接口标准化结果：保留核心字段并附带 raw_json 供回放清洗。
    lot_id: str
    title_raw: str
    description_raw: str | None
    end_time: str | None
    status: str
    current_price: str | None
    start_price: str | None
    bid_count: int | None
    look_count: int | None
    fee_rate: str | None
    winner: str | None
    bid_history_html: str | None
    image_primary: str | None
    images_json: str | None
    video_url: str | None
    labels_json: str | None
    raw_json: str


class HXParser:
    # 先尝试解析页面内 JSON 状态，再回退到 HTML 属性解析。
    SESSION_PATTERN = re.compile(
        r'<div[^>]*class="[^"]*session[^"]*"[^>]*data-session-id="(?P<session_id>[^"]+)"[^>]*data-session-type="(?P<session_type>[^"]+)"[^>]*data-end-time="(?P<end_time>[^"]*)"[^>]*>(?P<body>.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )

    LOT_PATTERN = re.compile(
        r'<div[^>]*class="[^"]*lot[^"]*"[^>]*data-lot-id="(?P<lot_id>[^"]+)"[^>]*data-session-id="(?P<session_id>[^"]+)"[^>]*data-end-time="(?P<end_time>[^"]*)"[^>]*data-status="(?P<status>[^"]*)"[^>]*>(?P<body>.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )

    SCRIPT_STATE_PATTERN = re.compile(
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
        re.DOTALL,
    )

    def parse_sessions(self, html: str, source_url: str) -> list[ParsedSession]:
        # 解析专场列表。
        sessions = self._parse_state_sessions(html, source_url)
        if sessions:
            return sessions

        output: list[ParsedSession] = []
        for m in self.SESSION_PATTERN.finditer(html):
            title = clean_text(re.sub(r"<[^>]+>", " ", m.group("body")))
            output.append(
                ParsedSession(
                    session_id=m.group("session_id"),
                    session_type=clean_text(m.group("session_type")).upper() or "NORMAL",
                    title=title or m.group("session_id"),
                    source_url=source_url,
                    scheduled_end_time=m.group("end_time") or None,
                )
            )
        return output

    def parse_lots(self, html: str) -> list[ParsedLot]:
        # 解析标的列表。
        lots = self._parse_state_lots(html)
        if lots:
            return lots

        output: list[ParsedLot] = []
        for m in self.LOT_PATTERN.finditer(html):
            body = m.group("body")
            title = clean_text(re.sub(r"<[^>]+>", " ", body))
            price = self._extract_attr(body, "data-current-price")
            bid_count_str = self._extract_attr(body, "data-bid-count")
            category = self._extract_attr(body, "data-category")
            grade_agency = self._extract_attr(body, "data-grade-agency")
            grade_score = self._extract_attr(body, "data-grade-score")
            description_raw = self._extract_attr(body, "data-description") or self._extract_attr(body, "data-desc")
            bid_count = int(bid_count_str) if bid_count_str and bid_count_str.isdigit() else None
            output.append(
                ParsedLot(
                    lot_id=m.group("lot_id"),
                    session_id=m.group("session_id"),
                    title_raw=title or m.group("lot_id"),
                    description_raw=clean_text(description_raw) or None,
                    end_time=m.group("end_time") or None,
                    status=normalize_status(m.group("status")),
                    current_price=str(parse_decimal(price)) if parse_decimal(price) is not None else None,
                    bid_count=bid_count,
                    category=clean_text(category) or None,
                    grade_agency=normalize_grade_agency(grade_agency),
                    grade_score=normalize_grade_score(grade_score),
                )
            )
        return output

    def _parse_state_sessions(self, html: str, source_url: str) -> list[ParsedSession]:
        # 从 window.__INITIAL_STATE__ 抽取 session 数据。
        state = self._extract_state_json(html)
        sessions = state.get("sessions") if isinstance(state, dict) else None
        if not isinstance(sessions, list):
            return []

        parsed: list[ParsedSession] = []
        for row in sessions:
            if not isinstance(row, dict):
                continue
            session_id = clean_text(str(row.get("session_id") or row.get("id") or ""))
            if not session_id:
                continue
            parsed.append(
                ParsedSession(
                    session_id=session_id,
                    session_type=clean_text(str(row.get("session_type") or "NORMAL")).upper(),
                    title=clean_text(str(row.get("title") or session_id)),
                    source_url=source_url,
                    scheduled_end_time=clean_text(str(row.get("scheduled_end_time") or "")) or None,
                )
            )
        return parsed

    def _parse_state_lots(self, html: str) -> list[ParsedLot]:
        # 从 window.__INITIAL_STATE__ 抽取 lot 数据。
        state = self._extract_state_json(html)
        lots = state.get("lots") if isinstance(state, dict) else None
        if not isinstance(lots, list):
            return []

        parsed: list[ParsedLot] = []
        for row in lots:
            if not isinstance(row, dict):
                continue
            lot_id = clean_text(str(row.get("lot_id") or row.get("id") or ""))
            session_id = clean_text(str(row.get("session_id") or ""))
            if not lot_id or not session_id:
                continue

            price = parse_decimal(str(row.get("current_price") or ""))
            bid_count_val = row.get("bid_count")
            bid_count = int(bid_count_val) if isinstance(bid_count_val, (int, str)) and str(bid_count_val).isdigit() else None

            parsed.append(
                ParsedLot(
                    lot_id=lot_id,
                    session_id=session_id,
                    title_raw=clean_text(str(row.get("title_raw") or row.get("title") or lot_id)),
                    description_raw=clean_text(
                        str(row.get("description_raw") or row.get("description") or row.get("itemdesc") or "")
                    )
                    or None,
                    end_time=clean_text(str(row.get("end_time") or "")) or None,
                    status=normalize_status(str(row.get("status") or "")),
                    current_price=str(price) if price is not None else None,
                    bid_count=bid_count,
                    category=clean_text(str(row.get("category") or "")) or None,
                    grade_agency=normalize_grade_agency(str(row.get("grade_agency") or "")),
                    grade_score=normalize_grade_score(str(row.get("grade_score") or "")),
                )
            )
        return parsed

    def _extract_state_json(self, html: str) -> dict[str, Any]:
        # 抽取并反序列化前端注入状态。
        match = self.SCRIPT_STATE_PATTERN.search(html)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            return {}
        return {}

    @staticmethod
    def _extract_attr(body: str, attr: str) -> str | None:
        pattern = re.compile(fr'{attr}="([^"]*)"', re.IGNORECASE)
        m = pattern.search(body)
        if not m:
            return None
        return clean_text(m.group(1))
