from __future__ import annotations

from datetime import datetime, timezone

from src.config.settings import AppConfig
from src.domain.events import EventType, SessionType, Task
from src.domain.models import AuctionSession
from src.scheduler.task_scheduler import TaskScheduler
from src.scraping.adapter import FetchContext, ScraplingAdapter
from src.scraping.normalizers import parse_datetime
from src.scraping.url_guard import is_hx_allowed_url
from src.storage.repositories.session_repo import SessionRepository
from src.workers.executors.types import ExecutorResult


class DiscoveryExecutor:
    def __init__(
        self,
        config: AppConfig,
        adapter: ScraplingAdapter,
        session_repo: SessionRepository,
        scheduler: TaskScheduler,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.session_repo = session_repo
        self.scheduler = scheduler

    def execute(self, task: Task) -> ExecutorResult:
        if task.event_type != EventType.DISCOVER_SESSIONS:
            return ExecutorResult(success=False, message=f"DISCOVERY_EXECUTOR 不支持任务类型: {task.event_type.value}")

        # 发现入口页并写入 session，同时派发 DISCOVER_LOTS 任务。
        url = task.payload.get("url") or task.entity_id
        if not isinstance(url, str) or not url:
            return ExecutorResult(success=False, message="DISCOVER_SESSIONS 缺少 url")

        raw = self.adapter.fetch_page(url, FetchContext())
        parsed_sessions = self.adapter.parse_session(raw)

        emitted = 0
        skipped_invalid_source = 0
        now = datetime.now(timezone.utc)
        for item in parsed_sessions:
            # 只允许目标站域名来源入库，避免测试/演示数据污染正式库。
            if not is_hx_allowed_url(item.source_url):
                skipped_invalid_source += 1
                continue

            scheduled_end = parse_datetime(item.scheduled_end_time)
            if scheduled_end and scheduled_end.tzinfo is None:
                scheduled_end = scheduled_end.replace(tzinfo=self.config.timezone)
            if scheduled_end:
                scheduled_end = scheduled_end.astimezone(timezone.utc)

            try:
                session_type = SessionType(item.session_type)
            except ValueError:
                session_type = SessionType.NORMAL

            session = AuctionSession(
                session_id=item.session_id,
                session_type=session_type,
                title=item.title,
                scheduled_end_time=scheduled_end,
                source_url=item.source_url,
                discovered_at=now,
                updated_at=now,
            )
            self.session_repo.upsert_session(session)

            emitted += len(self.scheduler.schedule_discover_lots(session.session_id, session.source_url, now))
            # 专场自动派发分段补抓任务（结标后、次日、可选 D+3）。
            if session.session_type == SessionType.SPECIAL:
                emitted += len(self.scheduler.schedule_session_scrapes(session, now))

        return ExecutorResult(
            success=True,
            processed_count=len(parsed_sessions) - skipped_invalid_source,
            emitted_task_count=emitted,
            message=f"发现 {len(parsed_sessions)} 个 session，过滤非目标域名 {skipped_invalid_source} 个",
        )
