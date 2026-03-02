from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Protocol

from src.config.settings import AppConfig
from src.domain.events import EventType, SnapshotType, Task
from src.scraping.adapter import FetchContext, ScraplingAdapter
from src.scraping.parsers.hx_parser import ParsedLotDetail
from src.scraping.normalizers import parse_decimal
from src.workers.executors.types import ExecutorResult
from src.workers.monitor.extension_monitor import ExtensionMonitor


class SnapshotServiceProtocol(Protocol):
    # 快照服务协议：执行器只依赖协议，不依赖具体实现。
    def save_from_parsed(
        self,
        lot_id: str,
        snapshot_type: SnapshotType,
        current_price,
        bid_count,
        raw_html: str,
        snapshot_time: datetime,
        session_id: str,
        quality_score: Decimal = Decimal("1.0"),
    ) -> None: ...


class ResultServiceProtocol(Protocol):
    # 结果服务协议：负责更新 lot_result。
    def upsert_from_snapshot(
        self,
        lot_id: str,
        final_price,
        final_end_time: datetime | None,
        confidence_score,
        decided_from_snapshot: str,
        is_unsold: bool = False,
        is_withdrawn: bool = False,
    ) -> None: ...


class SnapshotExecutor:
    # 缺失/隐藏场景写低质量分，便于后续质量看板识别。
    MISSING_SNAPSHOT_QUALITY = Decimal("0.10")
    DETAIL_FALLBACK_QUALITY = Decimal("0.60")

    # 原始状态关键词：用于识别撤拍/流拍等“页面不展示但已终态”场景。
    WITHDRAWN_KEYWORDS = ("撤拍", "已撤拍", "withdraw", "withdrawn", "隐藏", "下架", "删除")
    UNSOLD_KEYWORDS = ("流拍", "未成交", "未拍出", "unsold")

    def __init__(
        self,
        config: AppConfig,
        adapter: ScraplingAdapter,
        monitor: ExtensionMonitor,
        snapshot_service: SnapshotServiceProtocol,
        result_service: ResultServiceProtocol,
        reschedule_final_monitor: Callable[[Task, datetime, dict[str, object]], None] | None = None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.monitor = monitor
        self.snapshot_service = snapshot_service
        self.result_service = result_service
        # 生产环境可注入“延后再入队”回调，避免 FINAL 监控长时间占住 worker。
        self.reschedule_final_monitor = reschedule_final_monitor

    def execute(self, task: Task) -> ExecutorResult:
        # 根据事件类型分发到单次快照、最终监控或专场批量补抓。
        if task.event_type in {EventType.SNAPSHOT_PRE5, EventType.SNAPSHOT_PRE1}:
            return self._execute_single_snapshot(task)
        if task.event_type == EventType.SNAPSHOT_FINAL_MONITOR:
            return self._execute_final_monitor(task)
        if task.event_type == EventType.SESSION_FINAL_SCRAPE:
            return self._execute_session_final(task)
        return ExecutorResult(success=False, message=f"不支持的事件: {task.event_type}")

    def _execute_single_snapshot(self, task: Task) -> ExecutorResult:
        url = task.payload.get("url")
        lot_id = task.payload.get("lot_id") or task.entity_id
        session_id = task.payload.get("session_id")
        if not isinstance(url, str) or not isinstance(lot_id, str) or not isinstance(session_id, str):
            return ExecutorResult(success=False, message="快照任务缺少 url/lot_id/session_id")

        raw = self.adapter.fetch_page(url, FetchContext())
        lots = self.adapter.parse_lots(raw)
        target = self._find_target_lot(lots, lot_id, session_id)
        snapshot_type = SnapshotType.PRE5 if task.event_type == EventType.SNAPSHOT_PRE5 else SnapshotType.PRE1
        if target is None:
            # PRE 快照若列表里找不到 lot，优先尝试详情 API 回退；不再直接失败重试。
            detail = self.adapter.fetch_lot_detail(lot_id)
            return self._handle_missing_snapshot_with_detail_fallback(
                lot_id=lot_id,
                session_id=session_id,
                snapshot_type=snapshot_type,
                detail=detail,
            )

        price = parse_decimal(target.current_price)
        self.snapshot_service.save_from_parsed(
            lot_id=lot_id,
            snapshot_type=snapshot_type,
            current_price=price,
            bid_count=target.bid_count,
            raw_html=raw.text,
            snapshot_time=datetime.now(timezone.utc),
            session_id=session_id,
        )
        return ExecutorResult(success=True, processed_count=1, message=f"完成 {snapshot_type.value} 快照")

    def _execute_final_monitor(self, task: Task) -> ExecutorResult:
        if self.reschedule_final_monitor is None:
            return self._execute_final_monitor_blocking(task)
        return self._execute_final_monitor_nonblocking(task)

    def _execute_final_monitor_blocking(self, task: Task) -> ExecutorResult:
        url = task.payload.get("url")
        lot_id = task.payload.get("lot_id") or task.entity_id
        session_id = task.payload.get("session_id")
        if not isinstance(url, str) or not isinstance(lot_id, str) or not isinstance(session_id, str):
            return ExecutorResult(success=False, message="FINAL 监控缺少 url/lot_id/session_id")

        outcome = self.monitor.monitor(url=url, lot_id=lot_id, session_id=session_id)
        if outcome.lot is None:
            # FINAL 监控没找到 lot，尝试详情 API 兜底，并写入可追踪终态/缺失结果。
            detail = self.adapter.fetch_lot_detail(lot_id)
            return self._handle_missing_final_with_detail_fallback(
                lot_id=lot_id,
                session_id=session_id,
                detail=detail,
            )

        price = parse_decimal(outcome.lot.current_price)
        now = datetime.now(timezone.utc)
        self.snapshot_service.save_from_parsed(
            lot_id=lot_id,
            snapshot_type=SnapshotType.FINAL,
            current_price=price,
            bid_count=outcome.lot.bid_count,
            raw_html=f"<meta source='{url}'/>\\n",
            snapshot_time=now,
            session_id=session_id,
        )

        self.result_service.upsert_from_snapshot(
            lot_id=lot_id,
            final_price=price,
            final_end_time=now if outcome.closed else None,
            confidence_score=0.95 if outcome.closed else 0.75,
            decided_from_snapshot=SnapshotType.FINAL.value,
            is_unsold=price is None,
            is_withdrawn=False,
        )

        if outcome.timed_out:
            return ExecutorResult(success=True, processed_count=1, message="FINAL 监控超时，已写入非终态")
        return ExecutorResult(success=True, processed_count=1, message="FINAL 监控完成")

    def _execute_final_monitor_nonblocking(self, task: Task) -> ExecutorResult:
        # 非阻塞 FINAL 监控：每次只轮询一次，未闭合则延后重排同类任务。
        url = task.payload.get("url")
        lot_id = task.payload.get("lot_id") or task.entity_id
        session_id = task.payload.get("session_id")
        if not isinstance(url, str) or not isinstance(lot_id, str) or not isinstance(session_id, str):
            return ExecutorResult(success=False, message="FINAL 监控缺少 url/lot_id/session_id")

        now = datetime.now(timezone.utc)
        deadline = self._resolve_monitor_deadline(task.payload, now)
        # FINAL 场景优先使用单 lot 详情接口，避免每次全量解析整场列表导致高延迟。
        detail = self.adapter.fetch_lot_detail(lot_id)
        if detail is not None:
            price = parse_decimal(detail.current_price)
            status_text = self._extract_raw_status(detail.raw_json)
            is_withdrawn = self._is_withdrawn(status_text)
            is_unsold = self._is_unsold(status_text, detail.status, price, is_withdrawn)
            is_closed = detail.status == "closed"
            is_terminal = is_closed or is_withdrawn or is_unsold
            confidence = 0.92 if is_terminal else 0.70

            self.snapshot_service.save_from_parsed(
                lot_id=lot_id,
                snapshot_type=SnapshotType.FINAL,
                current_price=price,
                bid_count=detail.bid_count,
                raw_html=f"<meta source='detail_api_poll' status='{detail.status}' raw_status='{status_text}'/>",
                snapshot_time=now,
                session_id=session_id,
            )
            self.result_service.upsert_from_snapshot(
                lot_id=lot_id,
                final_price=price,
                final_end_time=now if is_closed else None,
                confidence_score=confidence,
                decided_from_snapshot=SnapshotType.FINAL.value,
                is_unsold=is_unsold,
                is_withdrawn=is_withdrawn,
            )
            if is_terminal:
                return ExecutorResult(success=True, processed_count=1, message="FINAL 监控完成")
        else:
            raw = self.adapter.fetch_page(url, FetchContext())
            lots = self.adapter.parse_lots(raw)
            target = self._find_target_lot(lots, lot_id, session_id)
            if target is None:
                return self._handle_missing_final_with_detail_fallback(
                    lot_id=lot_id,
                    session_id=session_id,
                    detail=None,
                )

            price = parse_decimal(target.current_price)
            is_closed = target.status == "closed"
            self.snapshot_service.save_from_parsed(
                lot_id=lot_id,
                snapshot_type=SnapshotType.FINAL,
                current_price=price,
                bid_count=target.bid_count,
                raw_html=f"<meta source='{url}'/>\\n",
                snapshot_time=now,
                session_id=session_id,
            )
            self.result_service.upsert_from_snapshot(
                lot_id=lot_id,
                final_price=price,
                final_end_time=now if is_closed else None,
                confidence_score=0.95 if is_closed else 0.70,
                decided_from_snapshot=SnapshotType.FINAL.value,
                is_unsold=price is None and is_closed,
                is_withdrawn=False,
            )
            if is_closed:
                return ExecutorResult(success=True, processed_count=1, message="FINAL 监控完成")

        if now >= deadline:
            return ExecutorResult(success=True, processed_count=1, message="FINAL 监控窗口结束，已写入非终态")

        assert self.reschedule_final_monitor is not None
        poll_seconds = max(int(self.config.schedule.extension_poll_seconds), 1)
        next_run = min(now + timedelta(seconds=poll_seconds), deadline)
        if next_run <= now:
            return ExecutorResult(success=True, processed_count=1, message="FINAL 监控窗口结束，已写入非终态")

        next_round = self._parse_int(task.payload.get("monitor_round"), default=0) + 1
        self.reschedule_final_monitor(
            task,
            next_run,
            {
                "monitor_deadline_at": deadline.isoformat(),
                "monitor_round": next_round,
            },
        )
        return ExecutorResult(success=True, processed_count=1, message=f"FINAL 未闭合，已延后第 {next_round} 轮监控")

    def _execute_session_final(self, task: Task) -> ExecutorResult:
        url = task.payload.get("url")
        session_id = task.entity_id
        if not isinstance(url, str):
            return ExecutorResult(success=False, message="SESSION_FINAL_SCRAPE 缺少 url")

        raw = self.adapter.fetch_page(url, FetchContext())
        lots = self.adapter.parse_lots(raw)
        processed = 0

        for lot in lots:
            if lot.session_id != session_id:
                continue
            price = parse_decimal(lot.current_price)
            now = datetime.now(timezone.utc)
            self.snapshot_service.save_from_parsed(
                lot_id=lot.lot_id,
                snapshot_type=SnapshotType.NEXTDAY_FIX,
                current_price=price,
                bid_count=lot.bid_count,
                raw_html=raw.text,
                snapshot_time=now,
                session_id=session_id,
            )
            self.result_service.upsert_from_snapshot(
                lot_id=lot.lot_id,
                final_price=price,
                final_end_time=now if lot.status == "closed" else None,
                confidence_score=0.9,
                decided_from_snapshot=SnapshotType.NEXTDAY_FIX.value,
                is_unsold=price is None,
                is_withdrawn=False,
            )
            processed += 1

        return ExecutorResult(success=True, processed_count=processed, message=f"专场补抓处理 {processed} 个 lot")

    @staticmethod
    def _find_target_lot(lots, lot_id: str, session_id: str):
        for lot in lots:
            if lot.lot_id == lot_id and lot.session_id == session_id:
                return lot
        return None

    def _handle_missing_snapshot_with_detail_fallback(
        self,
        lot_id: str,
        session_id: str,
        snapshot_type: SnapshotType,
        detail: ParsedLotDetail | None,
    ) -> ExecutorResult:
        # PRE 快照缺失处理：
        # 1) detail 不可用：写占位快照（保留证据）并成功返回，避免无效重试风暴；
        # 2) detail 可用：按 detail 生成快照；若判定撤拍/流拍则同步更新结果表。
        now = datetime.now(timezone.utc)
        if detail is None:
            self.snapshot_service.save_from_parsed(
                lot_id=lot_id,
                snapshot_type=snapshot_type,
                current_price=None,
                bid_count=None,
                raw_html=f"<meta missing='lot_not_found_or_hidden' lot_id='{lot_id}'/>",
                snapshot_time=now,
                session_id=session_id,
                quality_score=self.MISSING_SNAPSHOT_QUALITY,
            )
            return ExecutorResult(success=True, processed_count=1, message=f"{snapshot_type.value} 未找到 lot，已写占位快照")

        price = parse_decimal(detail.current_price)
        status_text = self._extract_raw_status(detail.raw_json)
        is_withdrawn = self._is_withdrawn(status_text)
        is_unsold = self._is_unsold(status_text, detail.status, price, is_withdrawn)

        self.snapshot_service.save_from_parsed(
            lot_id=lot_id,
            snapshot_type=snapshot_type,
            current_price=price,
            bid_count=detail.bid_count,
            raw_html=f"<meta fallback='detail_api' status='{detail.status}' raw_status='{status_text}'/>",
            snapshot_time=now,
            session_id=session_id,
            quality_score=self.DETAIL_FALLBACK_QUALITY,
        )

        if is_withdrawn or is_unsold:
            self.result_service.upsert_from_snapshot(
                lot_id=lot_id,
                final_price=price,
                final_end_time=now if detail.status == "closed" else None,
                confidence_score=0.85 if is_withdrawn else 0.75,
                decided_from_snapshot=snapshot_type.value,
                is_unsold=is_unsold,
                is_withdrawn=is_withdrawn,
            )

        return ExecutorResult(
            success=True,
            processed_count=1,
            message=f"{snapshot_type.value} 通过详情回退完成（withdrawn={is_withdrawn}, unsold={is_unsold})",
        )

    def _handle_missing_final_with_detail_fallback(
        self,
        lot_id: str,
        session_id: str,
        detail: ParsedLotDetail | None,
    ) -> ExecutorResult:
        # FINAL 缺失处理：
        # - detail 不可用：写 FINAL 占位快照 + 低置信度非终态结果；
        # - detail 可用：写 FINAL 回退快照，并按撤拍/流拍/closed 决定终态字段。
        now = datetime.now(timezone.utc)
        if detail is None:
            self.snapshot_service.save_from_parsed(
                lot_id=lot_id,
                snapshot_type=SnapshotType.FINAL,
                current_price=None,
                bid_count=None,
                raw_html=f"<meta missing='final_lot_not_found_or_hidden' lot_id='{lot_id}'/>",
                snapshot_time=now,
                session_id=session_id,
                quality_score=self.MISSING_SNAPSHOT_QUALITY,
            )
            self.result_service.upsert_from_snapshot(
                lot_id=lot_id,
                final_price=None,
                final_end_time=None,
                confidence_score=0.20,
                decided_from_snapshot=SnapshotType.FINAL.value,
                is_unsold=False,
                is_withdrawn=False,
            )
            return ExecutorResult(success=True, processed_count=1, message="FINAL 未找到 lot，已写缺失快照与低置信度结果")

        price = parse_decimal(detail.current_price)
        status_text = self._extract_raw_status(detail.raw_json)
        is_withdrawn = self._is_withdrawn(status_text)
        is_unsold = self._is_unsold(status_text, detail.status, price, is_withdrawn)
        is_closed = detail.status == "closed"
        confidence = Decimal("0.90") if (is_withdrawn or is_unsold or is_closed) else Decimal("0.60")

        self.snapshot_service.save_from_parsed(
            lot_id=lot_id,
            snapshot_type=SnapshotType.FINAL,
            current_price=price,
            bid_count=detail.bid_count,
            raw_html=f"<meta fallback='detail_api_final' status='{detail.status}' raw_status='{status_text}'/>",
            snapshot_time=now,
            session_id=session_id,
            quality_score=self.DETAIL_FALLBACK_QUALITY,
        )
        self.result_service.upsert_from_snapshot(
            lot_id=lot_id,
            final_price=price,
            final_end_time=now if is_closed else None,
            confidence_score=confidence,
            decided_from_snapshot=SnapshotType.FINAL.value,
            is_unsold=is_unsold,
            is_withdrawn=is_withdrawn,
        )
        return ExecutorResult(
            success=True,
            processed_count=1,
            message=f"FINAL 详情回退完成（withdrawn={is_withdrawn}, unsold={is_unsold}, closed={is_closed})",
        )

    @staticmethod
    def _extract_raw_status(raw_json: str | None) -> str:
        # 从详情 raw_json 中读取最原始状态词，便于撤拍/流拍判定。
        if not raw_json:
            return ""
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            return ""
        if not isinstance(parsed, dict):
            return ""
        for key in ("status", "itemstate", "state", "itemstatus"):
            value = parsed.get(key)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return ""

    def _is_withdrawn(self, raw_status: str) -> bool:
        lowered = raw_status.lower()
        return any(keyword in raw_status or keyword in lowered for keyword in self.WITHDRAWN_KEYWORDS)

    def _is_unsold(
        self,
        raw_status: str,
        normalized_status: str,
        price: Decimal | None,
        is_withdrawn: bool,
    ) -> bool:
        # 流拍判定优先使用状态词；其次 closed+无价格作为弱判定（排除撤拍）。
        lowered = raw_status.lower()
        if any(keyword in raw_status or keyword in lowered for keyword in self.UNSOLD_KEYWORDS):
            return True
        if not is_withdrawn and normalized_status == "closed" and price is None:
            return True
        return False

    def _resolve_monitor_deadline(self, payload: dict, now: datetime) -> datetime:
        # deadline 允许跨任务透传，首次执行则按配置窗口生成。
        candidate = self._parse_datetime(payload.get("monitor_deadline_at"))
        if candidate is not None:
            return candidate

        scheduled_end = self._parse_datetime(payload.get("scheduled_end_time"))
        base = scheduled_end or now
        deadline = base + timedelta(minutes=self.config.schedule.extension_max_minutes)
        return deadline if deadline > now else now

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _parse_int(value: object, default: int = 0) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.lstrip("-").isdigit():
                return int(text)
        return default
