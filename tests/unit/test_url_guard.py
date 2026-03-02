from __future__ import annotations

import unittest

from src.scraping.url_guard import is_hx_allowed_url


class UrlGuardTestCase(unittest.TestCase):
    def test_hx_domains_allowed(self) -> None:
        # 目标站点主域名与子域名应通过校验。
        self.assertTrue(is_hx_allowed_url("https://www.hxguquan.com/goods-list.html?gid=1"))
        self.assertTrue(is_hx_allowed_url("https://api.huaxiaguquan.com/v3/xpai/list.jsp"))

    def test_non_hx_domains_blocked(self) -> None:
        # 非目标域名应被拒绝，避免脏数据混入。
        self.assertFalse(is_hx_allowed_url("http://example.com/session"))
        self.assertFalse(is_hx_allowed_url("u"))
        self.assertFalse(is_hx_allowed_url(""))
        self.assertFalse(is_hx_allowed_url(None))


if __name__ == "__main__":
    unittest.main()
