from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable


def clean_text(value: str | None) -> str:
    # 统一压缩空白并去首尾空格。
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_status(value: str | None) -> str:
    # 平台原始状态值归一化为 bidding/closed/unknown。
    v = clean_text(value).lower()
    if v in {"closed", "已结标", "成交", "已结束", "流拍", "撤拍", "已撤拍"}:
        return "closed"
    if v in {"bidding", "进行中", "竞拍中", "拍卖中"}:
        return "bidding"
    return "unknown"


def parse_decimal(value: str | None) -> Decimal | None:
    # 清洗货币符号后解析价格。
    if value is None:
        return None
    text = clean_text(value)
    if not text:
        return None

    text = text.replace(",", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return None

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_datetime(value: str | None, formats: Iterable[str] | None = None) -> datetime | None:
    # 支持 ISO 与常见日期格式解析。
    if not value:
        return None

    text = clean_text(value)
    if not text:
        return None

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    fmts = list(formats or ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"])
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def normalize_grade_score(value: str | None) -> str | None:
    text = clean_text(value)
    return text or None


def normalize_grade_agency(value: str | None) -> str | None:
    text = clean_text(value).upper()
    if not text:
        return None
    mapping = {
        "PCGS": "PCGS",
        "NGC": "NGC",
        "华夏": "HUAXIA",
        "HUAXIA": "HUAXIA",
    }
    return mapping.get(text, text)
