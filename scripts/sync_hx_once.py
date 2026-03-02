from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 允许从项目根目录直接运行该脚本，确保能导入 src 包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import AppConfig
from src.domain.events import SessionType
from src.domain.models import AuctionSession, Lot, LotClassification, LotDetail, LotStructured, ReviewQueueItem
from src.classification.lot_classifier_agent import LotClassifierAgent
from src.scraping.adapter import FetchContext, ScraplingAdapter
from src.scraping.normalizers import parse_datetime, parse_decimal
from src.scraping.url_guard import is_hx_allowed_url
from src.storage.db import Database
from src.storage.repositories.lot_classification_repo import LotClassificationRepository
from src.storage.repositories.lot_detail_repo import LotDetailRepository
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.lot_structured_repo import LotStructuredRepository
from src.storage.repositories.review_queue_repo import ReviewQueueRepository
from src.storage.repositories.session_repo import SessionRepository
from src.structuring.title_description_structured_agent import TitleDescriptionStructuredAgent


def parse_args() -> argparse.Namespace:
    # 单次同步参数：入口地址与抓取范围。
    parser = argparse.ArgumentParser(description="华夏古泉单次同步（含拍品详情）")
    parser.add_argument("--entry-url", default="https://www.hxguquan.com/", help="专场发现入口")
    parser.add_argument("--max-sessions", type=int, default=0, help="最多同步多少个专场，0 表示不限制")
    parser.add_argument("--max-lots-per-session", type=int, default=0, help="每个专场最多同步多少个拍品，0 表示不限制")
    return parser.parse_args()


def _normalize_utc(dt_value: datetime | None, timezone_name) -> datetime | None:
    # 将本地时间字段转换为 UTC，统一入库时区。
    if dt_value is None:
        return None
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone_name)
    return dt_value.astimezone(timezone.utc)


def run() -> None:
    # 单次全量同步：发现专场 -> 发现拍品 -> 抓详情并入库。
    args = parse_args()
    config = AppConfig.from_env()

    db = Database(config)
    db.init_schema()

    session_repo = SessionRepository(db)
    lot_repo = LotRepository(db)
    detail_repo = LotDetailRepository(db)
    classification_repo = LotClassificationRepository(db)
    structured_repo = LotStructuredRepository(db)
    review_queue_repo = ReviewQueueRepository(db)
    classifier_agent = LotClassifierAgent()
    structured_agent = TitleDescriptionStructuredAgent(
        # 单次同步默认走 LLM 主流程。
        enable_llm=True,
        settings_path=config.model_settings_path,
    )
    adapter = ScraplingAdapter(min_fetch_interval_seconds=config.queue.request_interval_seconds)

    now = datetime.now(timezone.utc)
    discovery_page = adapter.fetch_page(args.entry_url, FetchContext())
    parsed_sessions = adapter.parse_session(discovery_page)
    if args.max_sessions > 0:
        parsed_sessions = parsed_sessions[: args.max_sessions]

    session_count = 0
    lot_count = 0
    detail_count = 0
    classification_count = 0
    structured_count = 0
    review_count = 0
    for parsed_session in parsed_sessions:
        # 额外防护：只处理华夏域名的专场链接。
        if not is_hx_allowed_url(parsed_session.source_url):
            print(f"跳过非目标域名专场: session_id={parsed_session.session_id}, url={parsed_session.source_url}")
            continue

        try:
            session_type = SessionType(parsed_session.session_type)
        except ValueError:
            session_type = SessionType.NORMAL
        scheduled_end = _normalize_utc(parse_datetime(parsed_session.scheduled_end_time), config.timezone)

        session = AuctionSession(
            session_id=parsed_session.session_id,
            session_type=session_type,
            title=parsed_session.title,
            scheduled_end_time=scheduled_end,
            source_url=parsed_session.source_url,
            discovered_at=now,
            updated_at=now,
        )
        session_repo.upsert_session(session)
        session_count += 1

        lot_page = adapter.fetch_page(session.source_url, FetchContext())
        parsed_lots = adapter.parse_lots(lot_page)
        if args.max_lots_per_session > 0:
            parsed_lots = parsed_lots[: args.max_lots_per_session]

        for parsed_lot in parsed_lots:
            end_time = _normalize_utc(parse_datetime(parsed_lot.end_time), config.timezone)
            lot = Lot(
                lot_id=parsed_lot.lot_id,
                session_id=session.session_id,
                title_raw=parsed_lot.title_raw,
                description_raw=parsed_lot.description_raw,
                category=parsed_lot.category,
                grade_agency=parsed_lot.grade_agency,
                grade_score=parsed_lot.grade_score,
                end_time=end_time,
                status=parsed_lot.status,
                last_seen_at=now,
                updated_at=now,
            )
            lot_repo.upsert_lot(lot)
            lot_count += 1

            parsed_detail = adapter.fetch_lot_detail(parsed_lot.lot_id)
            if parsed_detail is None:
                continue
            detail_end_time = _normalize_utc(parse_datetime(parsed_detail.end_time), config.timezone)
            detail = LotDetail(
                lot_id=parsed_detail.lot_id,
                title_raw=parsed_detail.title_raw,
                description_raw=parsed_detail.description_raw,
                current_price=parse_decimal(parsed_detail.current_price),
                start_price=parse_decimal(parsed_detail.start_price),
                end_time=detail_end_time,
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
            detail_repo.upsert_detail(detail)
            detail_count += 1

            # 每个拍品详情写库后立即执行分类，并单独存储分类结果。
            classification_result = classifier_agent.classify(
                title=parsed_lot.title_raw,
                description=parsed_detail.description_raw or parsed_lot.description_raw,
                labels_json=parsed_detail.labels_json,
                session_title=parsed_lot.category,
            )
            classification = LotClassification(
                lot_id=parsed_lot.lot_id,
                category_l1=classification_result.category_l1,
                category_l2=classification_result.category_l2,
                tags_json=json.dumps(classification_result.tags, ensure_ascii=False) if classification_result.tags else None,
                rule_hit=classification_result.rule_hit,
                confidence_score=classification_result.confidence_score,
                classifier_version=classifier_agent.VERSION,
                updated_at=now,
            )
            classification_repo.upsert_classification(classification)
            classification_count += 1
            if classification_result.category_l1 != "未分类":
                lot.category = classification_result.category_l1
                lot.updated_at = now
                lot_repo.upsert_lot(lot)

            # 标题/描述结构化清洗：输出 schema 化字段并按置信度写入复核队列。
            structured_result = structured_agent.clean(
                lot_id=parsed_lot.lot_id,
                title=parsed_lot.title_raw,
                description=parsed_detail.description_raw or parsed_lot.description_raw,
                labels_json=parsed_detail.labels_json,
                category_hint=classification_result.category_l1,
            )
            structured = LotStructured(
                lot_id=parsed_lot.lot_id,
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
            structured_repo.upsert_structured(structured)
            structured_count += 1

            if structured_result.needs_manual_review:
                review_item = ReviewQueueItem(
                    review_id=f"review_structured_{parsed_lot.lot_id}",
                    queue_type="STRUCTURED_CLEANING",
                    entity_type="lot",
                    entity_id=parsed_lot.lot_id,
                    reason=structured_result.review_reason or "结构化清洗低置信度",
                    confidence_score=structured_result.confidence_score,
                    payload_json=json.dumps(
                        {
                            "lot_id": parsed_lot.lot_id,
                            "title": parsed_lot.title_raw,
                            "structured": structured_result.to_payload(),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                review_queue_repo.upsert_pending(review_item)
                review_count += 1
            else:
                review_queue_repo.resolve(
                    queue_type="STRUCTURED_CLEANING",
                    entity_type="lot",
                    entity_id=parsed_lot.lot_id,
                )

        print(f"同步专场完成: session_id={session.session_id}, lot={len(parsed_lots)}")

    print(
        "同步完成: "
        f"sessions={session_count}, lots={lot_count}, details={detail_count}, "
        f"classifications={classification_count}, structured={structured_count}, review={review_count}"
    )


if __name__ == "__main__":
    run()
