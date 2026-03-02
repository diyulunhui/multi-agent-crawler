from __future__ import annotations

import json
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Mapping
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from src.scraping.normalizers import clean_text, normalize_status, parse_decimal
from src.scraping.parsers.hx_parser import HXParser, ParsedLot, ParsedLotDetail, ParsedSession


@dataclass
class FetchContext:
    # 抓取上下文：可覆盖请求头和超时时间。
    headers: Mapping[str, str] | None = None
    timeout_seconds: int = 15


@dataclass
class RawPage:
    # 原始页面对象，供解析与证据落盘复用。
    url: str
    status_code: int
    text: str
    fetched_at: datetime
    headers: dict[str, str]


class ScraplingAdapter:
    """
    合规采集适配层：
    - 使用公开入口抓取页面
    - 不包含任何绕过风控逻辑
    - 输出统一 RawPage + Parsed* 结构
    """

    HX_BASE = "https://api.huaxiaguquan.com"
    HX_MEDIA_BASE = "https://imgali.huaxiaguquan.com"
    HX_QGRADING_BASE = "https://qgrading.huaxiaguquan.com"

    def __init__(self, user_agent: str = "crawler/1.0", min_fetch_interval_seconds: float = 2.0) -> None:
        self.user_agent = user_agent
        # 全局抓取节流：确保两次请求间隔不低于设定值。
        self.min_fetch_interval_seconds = min_fetch_interval_seconds
        self._last_fetch_monotonic = 0.0
        self._throttle_lock = Lock()

        # cid 缓存，减少重复请求认证接口。
        self._cid_lock = Lock()
        self._hx_cid: str | None = None
        self._hx_cid_expire_monotonic: float = 0.0

        self.parser = HXParser()

    def fetch_page(self, url: str, context: FetchContext | None = None) -> RawPage:
        # 统一请求入口，便于后续替换为 Scrapling Spider 实现。
        ctx = context or FetchContext()
        headers = {"User-Agent": self.user_agent}
        if ctx.headers:
            headers.update(dict(ctx.headers))

        req = Request(url=url, headers=headers, method="GET")
        status_code, content, response_headers = self._open_text(req, ctx.timeout_seconds)

        return RawPage(
            url=url,
            status_code=status_code,
            text=content,
            fetched_at=datetime.now(timezone.utc),
            headers=response_headers,
        )

    def _throttle(self) -> None:
        # 请求频率限制：未达到间隔时先等待。
        with self._throttle_lock:
            now = time.monotonic()
            elapsed = now - self._last_fetch_monotonic
            remain = self.min_fetch_interval_seconds - elapsed
            if remain > 0:
                time.sleep(remain)
            self._last_fetch_monotonic = time.monotonic()

    def _open_text(self, request: Request, timeout_seconds: int) -> tuple[int, str, dict[str, str]]:
        # 统一网络读取；若本机证书链异常，回退到不校验证书模式（仅用于拉公开数据）。
        self._throttle()
        try:
            with urlopen(request, timeout=timeout_seconds) as resp:
                return (
                    int(getattr(resp, "status", 200)),
                    resp.read().decode("utf-8", errors="ignore"),
                    {k: v for k, v in resp.headers.items()},
                )
        except Exception as exc:
            if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                raise

        insecure_context = ssl._create_unverified_context()
        with urlopen(request, timeout=timeout_seconds, context=insecure_context) as resp:
            return (
                int(getattr(resp, "status", 200)),
                resp.read().decode("utf-8", errors="ignore"),
                {k: v for k, v in resp.headers.items()},
            )

    def _fetch_jsonp(self, url: str, data: dict[str, str] | None = None) -> dict:
        # 调用 JSONP 接口并提取其中 JSON 内容。
        payload = urlencode(data).encode("utf-8") if data else None
        req = Request(url=url, data=payload, headers={"User-Agent": self.user_agent}, method="POST")
        _, text, _ = self._open_text(req, timeout_seconds=20)

        match = re.search(r"\((\{.*\})\)\s*;?\s*$", text, flags=re.DOTALL)
        if not match:
            return {}

        try:
            parsed = json.loads(match.group(1))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _fetch_json(self, url: str, params: dict[str, str] | None = None) -> dict:
        # 调用普通 JSON 接口并反序列化响应。
        full_url = url
        if params:
            query = urlencode(params)
            full_url = f"{url}?{query}"
        req = Request(url=full_url, headers={"User-Agent": self.user_agent}, method="GET")
        _, text, _ = self._open_text(req, timeout_seconds=20)
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _is_hx_website(self, url: str) -> bool:
        # 判断是否为华夏网站页面。
        host = (urlsplit(url).netloc or "").lower()
        return host.endswith("hxguquan.com") or host.endswith("huaxiaguquan.com")

    def _extract_gid(self, url: str) -> str | None:
        # 从 goods-list URL 中提取 gid。
        query = parse_qs(urlsplit(url).query)
        gid = query.get("gid", [None])[0]
        if gid is None:
            return None
        gid_text = clean_text(str(gid))
        return gid_text or None

    @staticmethod
    def _as_int(value: object) -> int | None:
        # 将接口字段转为 int，失败返回 None。
        text = clean_text(str(value or ""))
        return int(text) if text.isdigit() else None

    @staticmethod
    def _as_decimal_text(value: object) -> str | None:
        # 将价格等字段规范成 Decimal 字符串，便于后续写库。
        parsed = parse_decimal(str(value or ""))
        return str(parsed) if parsed is not None else None

    def _build_hx_media_url(self, path: str | None, media_type: str) -> str | None:
        # 将接口返回的相对路径拼成完整媒体 URL。
        normalized = clean_text(path or "")
        if not normalized:
            return None
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized
        base = f"{self.HX_MEDIA_BASE}/pic" if media_type == "image" else f"{self.HX_MEDIA_BASE}/video"
        return f"{base}/{normalized.lstrip('/')}"

    def _parse_media_list(self, payload: dict, key: str, media_type: str) -> list[str]:
        # 兼容 list / 字符串两种格式的媒体字段，并统一为 URL 列表。
        value = payload.get(key)
        items: list[str] = []
        if isinstance(value, list):
            for raw in value:
                url = self._build_hx_media_url(str(raw), media_type)
                if url:
                    items.append(url)
            return items
        if isinstance(value, str):
            for raw in re.split(r"[,\s|]+", value):
                url = self._build_hx_media_url(raw, media_type)
                if url:
                    items.append(url)
        return items

    def _get_hx_cid(self) -> str:
        # 获取并缓存 cid。
        with self._cid_lock:
            now = time.monotonic()
            if self._hx_cid and now < self._hx_cid_expire_monotonic:
                return self._hx_cid

            data = self._fetch_jsonp(
                f"{self.HX_BASE}/v3/auth/cid.jsp?jscall=?",
                {"app": "H5", "v": "1.0.0"},
            )
            cid = clean_text(str(data.get("cid") or ""))
            if data.get("error") != "0" or not cid:
                raise RuntimeError(f"获取 hx cid 失败: {data}")

            self._hx_cid = cid
            self._hx_cid_expire_monotonic = now + 600
            return cid

    def _parse_hx_sessions_via_api(self) -> list[ParsedSession]:
        # 通过专场接口抓取限时竞买专场，并合并普通拍卖分组发现。
        cid = self._get_hx_cid()
        data = self._fetch_jsonp(
            f"{self.HX_BASE}/v3/xpai/list.jsp?jscall=?",
            {"cid": cid},
        )
        if data.get("error") != "0":
            return []

        groups = data.get("grouplist")
        if not isinstance(groups, list):
            return []

        special_sessions: list[ParsedSession] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            gid = clean_text(str(group.get("groupId") or ""))
            if not gid:
                continue

            name = clean_text(str(group.get("groupName") or gid))
            gdate = clean_text(str(group.get("gdate") or "")) or None
            special_sessions.append(
                ParsedSession(
                    session_id=gid,
                    session_type="SPECIAL",
                    title=name,
                    source_url=f"https://www.hxguquan.com/goods-list.html?gid={gid}",
                    scheduled_end_time=gdate,
                )
            )

        # 普通拍卖分组来自 qgrading 检索接口，按 groupid 聚合为 NORMAL session。
        normal_sessions = self._parse_hx_normal_sessions_via_search()

        # 先放 NORMAL，再用 SPECIAL 覆盖同 id，避免专场被误降级。
        merged: dict[str, ParsedSession] = {s.session_id: s for s in normal_sessions}
        for session in special_sessions:
            merged[session.session_id] = session
        return list(merged.values())

    def _parse_hx_normal_sessions_via_search(self, max_pages: int = 2, page_size: int = 200) -> list[ParsedSession]:
        # 从普通拍卖搜索接口提取分组，补充 NORMAL session 发现能力。
        cid = self._get_hx_cid()
        sessions_by_gid: dict[str, ParsedSession] = {}

        for page in range(1, max_pages + 1):
            data = self._fetch_json(
                f"{self.HX_QGRADING_BASE}/priceSearch/solrQueryVif",
                {
                    "auctionStatus": "0",
                    "cid": cid,
                    "type": "",
                    "gname": "",
                    "groupid": "",
                    "pageSize": str(page_size),
                    "pageNum": str(page),
                    "startingPrice": "0",
                    "closingPrice": "",
                    "startTime": "",
                    "endTime": "",
                },
            )
            if str(data.get("code")) != "200":
                break

            rows = data.get("data")
            if not isinstance(rows, list) or not rows:
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue
                gid = clean_text(str(row.get("groupid") or ""))
                if not gid or gid in sessions_by_gid:
                    continue

                # pgname 常见格式：{专场名}<br>{日期结标描述}，优先取首行标题。
                pgname = str(row.get("pgname") or "")
                title = clean_text(re.split(r"<br\s*/?>", pgname, flags=re.IGNORECASE)[0])
                if not title:
                    title = clean_text(str(row.get("gname") or gid))

                gdate = clean_text(str(row.get("gdate") or "")) or None
                sessions_by_gid[gid] = ParsedSession(
                    session_id=gid,
                    session_type="NORMAL",
                    title=title or gid,
                    source_url=f"https://www.hxguquan.com/goods-list.html?gid={gid}",
                    scheduled_end_time=gdate,
                )

            total_page = self._as_int(data.get("totalPage"))
            if total_page is not None and page >= total_page:
                break

        return list(sessions_by_gid.values())

    def _parse_hx_lots_via_api(self, gid: str) -> list[ParsedLot]:
        # 通过专场详情接口分页抓取 lot 列表。
        cid = self._get_hx_cid()
        page = 1
        lots: list[ParsedLot] = []

        while page <= 50:
            data = self._fetch_jsonp(
                f"{self.HX_BASE}/v3/xpai/group.jsp?jscall=?",
                {
                    "cid": cid,
                    "gid": gid,
                    "pid": str(page),
                    "gtype": "",
                    "order": "20",
                },
            )
            if data.get("error") != "0":
                break

            items = data.get("items")
            if not isinstance(items, list) or not items:
                break

            session_id = clean_text(str(data.get("gid") or gid)) or gid
            group_name = clean_text(str(data.get("gname") or "")) or None
            group_end_time = clean_text(str(data.get("gdate") or "")) or None

            for item in items:
                if not isinstance(item, dict):
                    continue

                lot_id = clean_text(str(item.get("itemcode") or item.get("id") or ""))
                if not lot_id:
                    continue

                price = parse_decimal(str(item.get("itemcprice") or ""))
                bid_count_raw = item.get("itemtimes") or item.get("bidcount")
                bid_count = int(str(bid_count_raw)) if str(bid_count_raw).isdigit() else None

                end_time = clean_text(str(item.get("itemedate") or item.get("edate") or "")) or group_end_time
                status_raw = item.get("itemstate") or item.get("status") or "bidding"

                lots.append(
                    ParsedLot(
                        lot_id=lot_id,
                        session_id=session_id,
                        title_raw=clean_text(str(item.get("itemname") or lot_id)),
                        description_raw=clean_text(str(item.get("itemdesc") or item.get("itemmemo") or "")) or None,
                        end_time=end_time,
                        status=normalize_status(str(status_raw) or "bidding"),
                        current_price=str(price) if price is not None else None,
                        bid_count=bid_count,
                        category=group_name,
                        grade_agency=None,
                        grade_score=None,
                    )
                )

            if len(items) < 60:
                break
            page += 1

        return lots

    def _parse_hx_lot_detail_via_api(self, lot_id: str) -> ParsedLotDetail | None:
        # 通过 item 接口抓取拍品详情并标准化输出。
        cid = self._get_hx_cid()
        data = self._fetch_jsonp(
            f"{self.HX_BASE}/v3/xpai/item.jsp?jscall=?",
            {"cid": cid, "itemcode": lot_id},
        )
        if data.get("error") != "0":
            return None

        # 接口会返回 pic + pics，多源合并去重后保留完整图片列表。
        image_urls = self._parse_media_list(data, "pics", "image")
        primary_image_url = self._build_hx_media_url(str(data.get("pic") or ""), "image")
        if primary_image_url:
            image_urls = [primary_image_url, *[u for u in image_urls if u != primary_image_url]]

        # labels 可能是列表或字符串，统一转 JSON 文本存库。
        labels_raw = data.get("labels")
        if isinstance(labels_raw, list):
            labels_json = json.dumps([clean_text(str(v)) for v in labels_raw if clean_text(str(v))], ensure_ascii=False)
        else:
            labels_text = clean_text(str(labels_raw or ""))
            labels_json = json.dumps([labels_text], ensure_ascii=False) if labels_text else None

        video_url = self._build_hx_media_url(str(data.get("video") or ""), "video")
        payload_json = json.dumps(data, ensure_ascii=False, sort_keys=True)

        return ParsedLotDetail(
            lot_id=clean_text(str(data.get("itemcode") or lot_id)) or lot_id,
            title_raw=clean_text(str(data.get("itemname") or lot_id)),
            description_raw=clean_text(str(data.get("itemdesc") or "")) or None,
            end_time=clean_text(str(data.get("itemdate") or "")) or None,
            status=normalize_status(str(data.get("status") or "unknown")),
            current_price=self._as_decimal_text(data.get("itemcprice")),
            start_price=self._as_decimal_text(data.get("itemsprice")),
            bid_count=self._as_int(data.get("itembidc")),
            look_count=self._as_int(data.get("itemlookc")),
            fee_rate=self._as_decimal_text(data.get("feerate")),
            winner=clean_text(str(data.get("winner") or "")) or None,
            # 出价记录保留原始 HTML，便于后续按业务规则二次解析。
            bid_history_html=str(data.get("bidhistory") or "").strip() or None,
            image_primary=primary_image_url,
            images_json=json.dumps(image_urls, ensure_ascii=False) if image_urls else None,
            video_url=video_url,
            labels_json=labels_json,
            raw_json=payload_json,
        )

    def parse_session(self, raw: RawPage) -> list[ParsedSession]:
        # 专场发现解析：优先使用官网 API，失败时回退 HTML 解析。
        if self._is_hx_website(raw.url):
            try:
                sessions = self._parse_hx_sessions_via_api()
                if sessions:
                    return sessions
            except Exception:
                pass
        return self.parser.parse_sessions(raw.text, raw.url)

    def parse_lots(self, raw: RawPage) -> list[ParsedLot]:
        # 标的发现解析：优先使用官网 API，失败时回退 HTML 解析。
        if self._is_hx_website(raw.url):
            gid = self._extract_gid(raw.url)
            if gid:
                try:
                    lots = self._parse_hx_lots_via_api(gid)
                    if lots:
                        return lots
                except Exception:
                    pass
        return self.parser.parse_lots(raw.text)

    def fetch_lot_detail(self, lot_id: str) -> ParsedLotDetail | None:
        # 拉取单个拍品详情；仅对华夏站点启用官方接口。
        lot_code = clean_text(lot_id)
        if not lot_code:
            return None
        try:
            return self._parse_hx_lot_detail_via_api(lot_code)
        except Exception:
            return None
