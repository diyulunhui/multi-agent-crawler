from __future__ import annotations

import json
import unittest

from src.scraping.adapter import ScraplingAdapter


class HXAdapterDetailTestCase(unittest.TestCase):
    def test_parse_lot_detail_via_api(self) -> None:
        # 使用桩数据验证详情字段映射完整性。
        adapter = ScraplingAdapter(min_fetch_interval_seconds=0)
        adapter._get_hx_cid = lambda: "cid_test"  # type: ignore[method-assign]

        def fake_fetch_jsonp(url: str, data: dict[str, str] | None = None) -> dict:
            return {
                "error": "0",
                "itemcode": "lot-1",
                "itemname": "测试拍品",
                "itemdesc": "测试描述",
                "itemdate": "2026-02-28 20:30:15",
                "status": "拍卖中",
                "itemcprice": "12345",
                "itemsprice": "10000",
                "itembidc": "8",
                "itemlookc": "56",
                "feerate": "4.5",
                "winner": "",
                "bidhistory": "<ul><li>bid</li></ul>",
                "pic": "2026/0226/a.jpg",
                "pics": ["2026/0226/a.jpg", "2026/0226/b.jpg"],
                "video": "x/y.mp4",
                "labels": ["机制币", "银币"],
            }

        adapter._fetch_jsonp = fake_fetch_jsonp  # type: ignore[method-assign]
        detail = adapter._parse_hx_lot_detail_via_api("lot-1")

        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual("lot-1", detail.lot_id)
        self.assertEqual("测试拍品", detail.title_raw)
        self.assertEqual("测试描述", detail.description_raw)
        self.assertEqual("bidding", detail.status)
        self.assertEqual("12345", detail.current_price)
        self.assertEqual("10000", detail.start_price)
        self.assertEqual(8, detail.bid_count)
        self.assertEqual(56, detail.look_count)
        self.assertEqual("4.5", detail.fee_rate)
        self.assertIn("imgali.huaxiaguquan.com/pic", detail.image_primary or "")
        self.assertIn("imgali.huaxiaguquan.com/video", detail.video_url or "")
        self.assertEqual("<ul><li>bid</li></ul>", detail.bid_history_html)
        self.assertEqual(["机制币", "银币"], json.loads(detail.labels_json or "[]"))
        raw = json.loads(detail.raw_json)
        self.assertEqual("lot-1", raw["itemcode"])

    def test_parse_lot_detail_error_returns_none(self) -> None:
        # 接口返回 error 非 0 时应返回 None。
        adapter = ScraplingAdapter(min_fetch_interval_seconds=0)
        adapter._get_hx_cid = lambda: "cid_test"  # type: ignore[method-assign]
        adapter._fetch_jsonp = lambda url, data=None: {"error": "1"}  # type: ignore[method-assign]
        detail = adapter._parse_hx_lot_detail_via_api("lot-1")
        self.assertIsNone(detail)

    def test_parse_sessions_merge_special_and_normal_groups(self) -> None:
        # 专场列表应合并普通拍卖分组，并且 SPECIAL 优先覆盖同 gid。
        adapter = ScraplingAdapter(min_fetch_interval_seconds=0)
        adapter._get_hx_cid = lambda: "cid_test"  # type: ignore[method-assign]

        def fake_fetch_jsonp(url: str, data: dict[str, str] | None = None) -> dict:
            return {
                "error": "0",
                "grouplist": [
                    {"groupId": "74587", "groupName": "天津站机制币古钱专场", "gdate": "2026-02-28 20:30:00"}
                ],
            }

        def fake_fetch_json(url: str, params: dict[str, str] | None = None) -> dict:
            return {
                "code": "200",
                "totalPage": 1,
                "data": [
                    {
                        "groupid": "74587",
                        "pgname": "普通场同组<br>2月28日结标",
                        "gdate": "2026/02/28 20:30:00",
                        "gname": "lotA",
                    },
                    {
                        "groupid": "75041",
                        "pgname": "上海站普通场<br>3月01日结标",
                        "gdate": "2026/03/01 21:00:00",
                        "gname": "lotB",
                    },
                ],
            }

        adapter._fetch_jsonp = fake_fetch_jsonp  # type: ignore[method-assign]
        adapter._fetch_json = fake_fetch_json  # type: ignore[method-assign]
        sessions = adapter._parse_hx_sessions_via_api()
        by_id = {s.session_id: s for s in sessions}

        self.assertIn("74587", by_id)
        self.assertIn("75041", by_id)
        self.assertEqual("SPECIAL", by_id["74587"].session_type)
        self.assertEqual("NORMAL", by_id["75041"].session_type)
        self.assertEqual("天津站机制币古钱专场", by_id["74587"].title)
        self.assertEqual("上海站普通场", by_id["75041"].title)


if __name__ == "__main__":
    unittest.main()
