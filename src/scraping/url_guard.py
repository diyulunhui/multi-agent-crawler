from __future__ import annotations

from urllib.parse import urlsplit


ALLOWED_HX_DOMAINS = ("hxguquan.com", "huaxiaguquan.com")


def is_hx_allowed_url(url: str | None) -> bool:
    # 校验 URL 是否属于华夏站点（含子域名），用于防止测试数据混入正式库。
    if not isinstance(url, str):
        return False
    host = (urlsplit(url).netloc or "").lower().strip()
    if not host:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in ALLOWED_HX_DOMAINS)
