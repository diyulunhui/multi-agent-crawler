from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.config.settings import AppConfig
from src.domain.events import EventType, TaskPriority
from src.domain.models import AuctionSession, Lot


@dataclass(frozen=True)
class ScheduledEvent:
    # 规则引擎输出的任务描述（尚未持久化）。
    event_type: EventType
    entity_id: str
    run_at: datetime
    priority: TaskPriority
    payload: dict


class SchedulePolicy:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def discovery_events(self, now: datetime) -> list[ScheduledEvent]:
        # 周期性发现入口任务。
        return [
            ScheduledEvent(
                event_type=EventType.DISCOVER_SESSIONS,
                entity_id=self.config.site_name,
                run_at=now,
                priority=TaskPriority.DISCOVERY,
                payload={"site": self.config.site_name},
            )
        ]

    def lot_events(self, lot: Lot, now: datetime) -> list[ScheduledEvent]:
        # 普通拍卖：PRE5 / 可选 PRE1 / 可选 FINAL 监控任务。
        if lot.end_time is None:
            return []

        events: list[ScheduledEvent] = []
        status = (lot.status or "").strip().lower()
        # 拍前快照仅对“进行中”拍品有效；closed/withdrawn 等终态不再重复调度。
        should_schedule_pre = status in {"bidding", "running", "open"}

        if should_schedule_pre:
            pre5_at = lot.end_time - timedelta(minutes=self.config.schedule.pre5_minutes)
            events.append(
                ScheduledEvent(
                    event_type=EventType.SNAPSHOT_PRE5,
                    entity_id=lot.lot_id,
                    # 使用固定时间点，保证重复发现时 dedupe_key 稳定。
                    run_at=pre5_at,
                    priority=TaskPriority.PRE5,
                    payload={"snapshot_type": "PRE5", "scheduled_end_time": lot.end_time.isoformat()},
                )
            )

            if self.config.schedule.enable_pre1:
                pre1_at = lot.end_time - timedelta(minutes=self.config.schedule.pre1_minutes)
                events.append(
                    ScheduledEvent(
                        event_type=EventType.SNAPSHOT_PRE1,
                        entity_id=lot.lot_id,
                        # 使用固定时间点，保证重复发现时 dedupe_key 稳定。
                        run_at=pre1_at,
                        priority=TaskPriority.PRE1,
                        payload={"snapshot_type": "PRE1", "scheduled_end_time": lot.end_time.isoformat()},
                    )
                )

        if self.config.schedule.enable_final_monitor:
            events.append(
                ScheduledEvent(
                    event_type=EventType.SNAPSHOT_FINAL_MONITOR,
                    entity_id=lot.lot_id,
                    # 使用固定时间点，保证重复发现时 dedupe_key 稳定。
                    run_at=lot.end_time,
                    priority=TaskPriority.FINAL_MONITOR,
                    payload={"snapshot_type": "FINAL", "scheduled_end_time": lot.end_time.isoformat()},
                )
            )

        return events

    def session_events(self, session: AuctionSession, now: datetime) -> list[ScheduledEvent]:
        # 专场：结标后 + 次日 + 可选 D+3 分段补抓。
        if session.scheduled_end_time is None:
            return []

        events: list[ScheduledEvent] = []

        first_pull = session.scheduled_end_time + timedelta(minutes=self.config.schedule.special_post_close_minutes)
        events.append(
            ScheduledEvent(
                event_type=EventType.SESSION_FINAL_SCRAPE,
                entity_id=session.session_id,
                # 使用固定时间点，保证重复发现时 dedupe_key 稳定。
                run_at=first_pull,
                priority=TaskPriority.NEXTDAY_BACKFILL,
                payload={"stage": "POST_CLOSE", "url": session.source_url},
            )
        )

        session_tz = session.scheduled_end_time.astimezone(self.config.timezone)
        next_day_local = (session_tz + timedelta(days=1)).replace(
            hour=self.config.schedule.next_day_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        next_day = next_day_local.astimezone(timezone.utc)
        events.append(
            ScheduledEvent(
                event_type=EventType.SESSION_FINAL_SCRAPE,
                entity_id=session.session_id,
                # 使用固定时间点，保证重复发现时 dedupe_key 稳定。
                run_at=next_day,
                priority=TaskPriority.NEXTDAY_BACKFILL,
                payload={"stage": "NEXTDAY_FIX", "url": session.source_url},
            )
        )

        if self.config.schedule.enable_d3_backfill:
            d3_local = (session_tz + timedelta(days=3)).replace(
                hour=self.config.schedule.d3_hour,
                minute=0,
                second=0,
                microsecond=0,
            )
            d3 = d3_local.astimezone(timezone.utc)
            events.append(
                ScheduledEvent(
                    event_type=EventType.SESSION_FINAL_SCRAPE,
                    entity_id=session.session_id,
                    # 使用固定时间点，保证重复发现时 dedupe_key 稳定。
                    run_at=d3,
                    priority=TaskPriority.NEXTDAY_BACKFILL,
                    payload={"stage": "D3_BACKFILL", "url": session.source_url},
                )
            )

        return events
