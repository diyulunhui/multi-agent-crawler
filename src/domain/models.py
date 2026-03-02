from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from src.domain.events import EventType, SessionType, SnapshotType, TaskStatus


@dataclass
class AuctionSession:
    # 专场/普通场次主实体。
    session_id: str
    session_type: SessionType
    title: str
    scheduled_end_time: Optional[datetime]
    source_url: str
    discovered_at: datetime
    updated_at: datetime


@dataclass
class Lot:
    # 标的主实体，记录状态与结标时间。
    lot_id: str
    session_id: str
    title_raw: str
    description_raw: Optional[str]
    category: Optional[str]
    grade_agency: Optional[str]
    grade_score: Optional[str]
    end_time: Optional[datetime]
    status: str
    last_seen_at: datetime
    updated_at: datetime


@dataclass
class LotSnapshot:
    # 时间序列快照实体。
    snapshot_id: str
    lot_id: str
    snapshot_time: datetime
    snapshot_type: SnapshotType
    current_price: Optional[Decimal]
    bid_count: Optional[int]
    raw_ref: str
    quality_score: Decimal
    idempotency_key: str


@dataclass
class LotResult:
    # 标的最终结果实体。
    lot_id: str
    final_price: Optional[Decimal]
    final_end_time: Optional[datetime]
    is_withdrawn: bool
    is_unsold: bool
    confidence_score: Decimal
    decided_from_snapshot: str
    updated_at: datetime


@dataclass
class LotDetail:
    # 标的详情实体，保存详情页结构化字段与全量原始 JSON。
    lot_id: str
    title_raw: str
    description_raw: Optional[str]
    current_price: Optional[Decimal]
    start_price: Optional[Decimal]
    end_time: Optional[datetime]
    status: str
    bid_count: Optional[int]
    look_count: Optional[int]
    fee_rate: Optional[Decimal]
    winner: Optional[str]
    bid_history_html: Optional[str]
    image_primary: Optional[str]
    images_json: Optional[str]
    video_url: Optional[str]
    labels_json: Optional[str]
    raw_json: str
    fetched_at: datetime
    updated_at: datetime


@dataclass
class LotClassification:
    # 拍品分类实体，记录分类层级、命中规则与置信度。
    lot_id: str
    category_l1: str
    category_l2: Optional[str]
    tags_json: Optional[str]
    rule_hit: str
    confidence_score: Decimal
    classifier_version: str
    updated_at: datetime


@dataclass
class LotStructured:
    # 标题/描述结构化清洗结果，面向后续清洗分析与建模。
    lot_id: str
    coin_type: Optional[str]
    variety: Optional[str]
    mint_year: Optional[str]
    grading_company: Optional[str]
    grade_score: Optional[str]
    denomination: Optional[str]
    special_tags_json: Optional[str]
    confidence_score: Decimal
    extract_source: str
    schema_version: str
    raw_structured_json: str
    updated_at: datetime


@dataclass
class ReviewQueueItem:
    # 人工复核队列实体：低置信度或异常记录统一进入该表。
    review_id: str
    queue_type: str
    entity_type: str
    entity_id: str
    reason: str
    confidence_score: Decimal
    payload_json: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass
class TaskState:
    # 任务持久化状态实体。
    task_id: str
    event_type: EventType
    entity_id: str
    run_at: datetime
    priority: int
    status: TaskStatus
    retry_count: int
    max_retries: int
    last_error: Optional[str]
    dedupe_key: str
    payload: dict[str, Any]
    updated_at: datetime
