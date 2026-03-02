from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from src.classification.lot_classifier_agent import ClassificationResult, LotClassifierAgent
from src.config.settings import AppConfig
from src.domain.events import EventType, Task
from src.domain.models import Lot, LotClassification, LotDetail, LotStructured, ReviewQueueItem
from src.scheduler.task_scheduler import TaskScheduler
from src.scraping.adapter import FetchContext, ScraplingAdapter
from src.scraping.parsers.hx_parser import ParsedLotDetail
from src.scraping.normalizers import parse_datetime, parse_decimal
from src.scraping.url_guard import is_hx_allowed_url
from src.storage.repositories.review_queue_repo import ReviewQueueRepository
from src.storage.repositories.lot_classification_repo import LotClassificationRepository
from src.storage.repositories.lot_detail_repo import LotDetailRepository
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.lot_structured_repo import LotStructuredRepository
from src.structuring.title_description_structured_agent import TitleDescriptionStructuredAgent
from src.workers.executors.types import ExecutorResult


class LotDiscoveryExecutor:
    # 结构化清洗复核队列常量，统一用于写库与后续看板筛选。
    REVIEW_QUEUE_TYPE = "STRUCTURED_CLEANING"
    REVIEW_ENTITY_TYPE = "lot"

    def __init__(
        self,
        config: AppConfig,
        adapter: ScraplingAdapter,
        lot_repo: LotRepository,
        lot_detail_repo: LotDetailRepository,
        lot_classification_repo: LotClassificationRepository,
        lot_classifier_agent: LotClassifierAgent,
        structured_repo: LotStructuredRepository,
        review_queue_repo: ReviewQueueRepository,
        structured_agent: TitleDescriptionStructuredAgent,
        scheduler: TaskScheduler,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.lot_repo = lot_repo
        self.lot_detail_repo = lot_detail_repo
        self.lot_classification_repo = lot_classification_repo
        self.lot_classifier_agent = lot_classifier_agent
        self.structured_repo = structured_repo
        self.review_queue_repo = review_queue_repo
        self.structured_agent = structured_agent
        self.scheduler = scheduler

    def execute(self, task: Task) -> ExecutorResult:
        if task.event_type == EventType.STRUCTURE_LOT:
            return self._execute_structure_task(task)
        if task.event_type != EventType.DISCOVER_LOTS:
            return ExecutorResult(success=False, message=f"LOT_EXECUTOR 不支持任务类型: {task.event_type.value}")

        # 发现专场下所有 lot，并按规则派发快照任务。
        url = task.payload.get("url")
        session_id = task.payload.get("session_id") or task.entity_id
        if not isinstance(url, str) or not url:
            return ExecutorResult(success=False, message="DISCOVER_LOTS 缺少 url")
        if not isinstance(session_id, str) or not session_id:
            return ExecutorResult(success=False, message="DISCOVER_LOTS 缺少 session_id")
        # 任务 URL 非目标域名时直接拒绝执行，避免混入外部样例数据。
        if not is_hx_allowed_url(url):
            return ExecutorResult(success=False, message=f"DISCOVER_LOTS url 非目标站点: {url}")

        raw = self.adapter.fetch_page(url, FetchContext())
        parsed_lots = self.adapter.parse_lots(raw)

        now = datetime.now(timezone.utc)
        emitted = 0
        for item in parsed_lots:
            end_time = parse_datetime(item.end_time)
            if end_time and end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=self.config.timezone)
            if end_time:
                end_time = end_time.astimezone(timezone.utc)

            lot = Lot(
                lot_id=item.lot_id,
                session_id=session_id,
                title_raw=item.title_raw,
                description_raw=item.description_raw,
                category=item.category,
                grade_agency=item.grade_agency,
                grade_score=item.grade_score,
                end_time=end_time,
                status=item.status,
                last_seen_at=now,
                updated_at=now,
            )
            self.lot_repo.upsert_lot(lot)
            parsed_detail = self._sync_lot_detail(lot_id=lot.lot_id, now=now)
            classification_result = self._classify_lot(
                lot=lot,
                parsed_detail=parsed_detail,
                session_title=item.category,
                now=now,
            )
            emitted += len(self.scheduler.schedule_lot_structuring(lot_id=lot.lot_id, now=now))
            emitted += len(
                self.scheduler.schedule_lot_snapshots_with_payload(
                    lot,
                    now=now,
                    extra_payload={"url": url, "session_id": session_id, "lot_id": lot.lot_id},
                )
            )

        return ExecutorResult(
            success=True,
            processed_count=len(parsed_lots),
            emitted_task_count=emitted,
            message=f"发现 {len(parsed_lots)} 个 lot",
        )

    def _execute_structure_task(self, task: Task) -> ExecutorResult:
        # 异步结构化任务：从仓储读取 lot/detail/classification，独立完成清洗入库。
        lot_id = task.payload.get("lot_id") if isinstance(task.payload.get("lot_id"), str) else task.entity_id
        if not isinstance(lot_id, str) or not lot_id:
            return ExecutorResult(success=False, message="STRUCTURE_LOT 缺少 lot_id")

        lot = self.lot_repo.get_by_id(lot_id)
        if lot is None:
            return ExecutorResult(success=False, message=f"STRUCTURE_LOT lot 不存在: {lot_id}")
        detail = self.lot_detail_repo.get_by_lot_id(lot_id)
        classification_result = self._load_classification_for_structuring(lot)
        now = datetime.now(timezone.utc)
        self._structure_lot(
            lot=lot,
            detail=detail,
            classification_result=classification_result,
            now=now,
            use_react=True,
        )
        return ExecutorResult(success=True, processed_count=1, emitted_task_count=0, message=f"结构化完成: {lot_id}")

    def _sync_lot_detail(self, lot_id: str, now: datetime) -> ParsedLotDetail | None:
        # 发现到 lot 后立即补抓详情，满足“每个拍品详情入库”的需求。
        parsed_detail = self.adapter.fetch_lot_detail(lot_id)
        if parsed_detail is None:
            return None

        end_time = parse_datetime(parsed_detail.end_time)
        if end_time and end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=self.config.timezone)
        if end_time:
            end_time = end_time.astimezone(timezone.utc)

        detail = LotDetail(
            lot_id=parsed_detail.lot_id,
            title_raw=parsed_detail.title_raw,
            description_raw=parsed_detail.description_raw,
            current_price=parse_decimal(parsed_detail.current_price),
            start_price=parse_decimal(parsed_detail.start_price),
            end_time=end_time,
            status=parsed_detail.status,
            bid_count=parsed_detail.bid_count,
            look_count=parsed_detail.look_count,
            fee_rate=parse_decimal(parsed_detail.fee_rate),
            winner=parsed_detail.winner,
            bid_history_html=parsed_detail.bid_history_html,
            image_primary=parsed_detail.image_primary,
            images_json=parsed_detail.images_json,
            video_url=parsed_detail.video_url,
            labels_json=parsed_detail.labels_json,
            raw_json=parsed_detail.raw_json,
            fetched_at=now,
            updated_at=now,
        )
        self.lot_detail_repo.upsert_detail(detail)
        return parsed_detail

    def _classify_lot(
        self,
        lot: Lot,
        parsed_detail: ParsedLotDetail | None,
        session_title: str | None,
        now: datetime,
    ) -> ClassificationResult:
        # 分类智能体：按标题/描述/标签规则分类，并把结果单独存表。
        description_raw = (
            parsed_detail.description_raw
            if parsed_detail is not None and parsed_detail.description_raw
            else lot.description_raw
        )
        labels_json = parsed_detail.labels_json if parsed_detail is not None else None
        result = self.lot_classifier_agent.classify(
            title=lot.title_raw,
            description=description_raw,
            labels_json=labels_json,
            session_title=session_title,
        )
        classification = LotClassification(
            lot_id=lot.lot_id,
            category_l1=result.category_l1,
            category_l2=result.category_l2,
            tags_json=json.dumps(result.tags, ensure_ascii=False) if result.tags else None,
            rule_hit=result.rule_hit,
            confidence_score=result.confidence_score,
            classifier_version=self.lot_classifier_agent.VERSION,
            updated_at=now,
        )
        self.lot_classification_repo.upsert_classification(classification)

        # 回写一级分类到 lot.category，后续筛选和报表可直接使用。
        if result.category_l1 != "未分类":
            lot.category = result.category_l1
            lot.updated_at = now
            self.lot_repo.upsert_lot(lot)
        return result

    def _structure_lot(
        self,
        lot: Lot,
        detail: ParsedLotDetail | LotDetail | None,
        classification_result: ClassificationResult,
        now: datetime,
        use_react: bool = False,
    ) -> None:
        # 结构化清洗智能体：将标题/描述落为字段化数据，并处理低置信度复核。
        description_raw = (
            detail.description_raw
            if detail is not None and detail.description_raw
            else lot.description_raw
        )
        labels_json = detail.labels_json if detail is not None else None
        structured_result = self.structured_agent.clean(
            lot_id=lot.lot_id,
            title=lot.title_raw,
            description=description_raw,
            labels_json=labels_json,
            category_hint=classification_result.category_l1,
            use_react=use_react,
        )

        structured = LotStructured(
            lot_id=lot.lot_id,
            coin_type=structured_result.coin_type,
            variety=structured_result.variety,
            mint_year=structured_result.mint_year,
            grading_company=structured_result.grading_company,
            grade_score=structured_result.grade_score,
            denomination=structured_result.denomination,
            special_tags_json=json.dumps(structured_result.special_tags, ensure_ascii=False)
            if structured_result.special_tags
            else None,
            confidence_score=structured_result.confidence_score,
            extract_source=structured_result.extract_source,
            schema_version=structured_result.schema_version,
            raw_structured_json=structured_result.raw_payload_json,
            updated_at=now,
        )
        self.structured_repo.upsert_structured(structured)

        if structured_result.needs_manual_review:
            # 低置信度结果写入人工复核队列，后续可由页面或工单系统处理。
            review_payload = {
                "lot_id": lot.lot_id,
                "title": lot.title_raw,
                "description": description_raw,
                "labels_json": labels_json,
                "classification": {
                    "category_l1": classification_result.category_l1,
                    "category_l2": classification_result.category_l2,
                    "rule_hit": classification_result.rule_hit,
                },
                "structured": structured_result.to_payload(),
            }
            review_item = ReviewQueueItem(
                review_id=f"review_structured_{lot.lot_id}",
                queue_type=self.REVIEW_QUEUE_TYPE,
                entity_type=self.REVIEW_ENTITY_TYPE,
                entity_id=lot.lot_id,
                reason=structured_result.review_reason or "结构化清洗低置信度",
                confidence_score=structured_result.confidence_score,
                payload_json=json.dumps(review_payload, ensure_ascii=False, sort_keys=True),
                status="pending",
                created_at=now,
                updated_at=now,
            )
            self.review_queue_repo.upsert_pending(review_item)
        else:
            # 结果稳定时自动关闭历史复核单，减少人工队列噪音。
            self.review_queue_repo.resolve(
                queue_type=self.REVIEW_QUEUE_TYPE,
                entity_type=self.REVIEW_ENTITY_TYPE,
                entity_id=lot.lot_id,
            )

    def _load_classification_for_structuring(self, lot: Lot) -> ClassificationResult:
        # 异步结构化阶段优先复用已落库分类结果；缺失时回退 lot.category。
        saved = self.lot_classification_repo.get_by_lot_id(lot.lot_id)
        if saved is not None:
            return ClassificationResult(
                category_l1=saved.category_l1,
                category_l2=saved.category_l2,
                tags=[],
                rule_hit=saved.rule_hit,
                confidence_score=saved.confidence_score,
            )
        category = lot.category or "未分类"
        return ClassificationResult(
            category_l1=category,
            category_l2=None,
            tags=[],
            rule_hit="fallback:lot_category",
            confidence_score=Decimal("0.20"),
        )
