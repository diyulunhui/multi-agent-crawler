from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from src.config.settings import AppConfig
from src.domain.events import EventType, Task, TaskPriority
from src.scraping.parsers.hx_parser import ParsedSession
from src.workers.executors.discovery_executor import DiscoveryExecutor


class _FakeAdapter:
    def fetch_page(self, url, context=None):
        # 发现执行器仅依赖 raw.url/raw.text，这里提供最小桩对象。
        class Raw:
            pass

        raw = Raw()
        raw.url = url
        raw.text = "<html>discovery</html>"
        return raw

    def parse_session(self, raw):
        return [
            ParsedSession(
                session_id="s_special",
                session_type="SPECIAL",
                title="special session",
                source_url="https://www.hxguquan.com/goods-list.html?gid=1001",
                scheduled_end_time="2026-03-01 20:00:00",
            ),
            ParsedSession(
                session_id="s_normal",
                session_type="NORMAL",
                title="normal session",
                source_url="https://www.hxguquan.com/goods-list.html?gid=1002",
                scheduled_end_time="2026-03-02 20:00:00",
            ),
        ]


class _FakeSessionRepo:
    def __init__(self) -> None:
        self.saved = []

    def upsert_session(self, session) -> None:
        # 记录被写入的 session，供断言使用。
        self.saved.append(session)


class _FakeScheduler:
    def __init__(self) -> None:
        self.discover_lots_calls = []
        self.session_scrape_calls = []

    def schedule_discover_lots(self, session_id: str, source_url: str, now):
        # 每个 session 产生 1 个 discover_lots 任务。
        self.discover_lots_calls.append((session_id, source_url))
        return [object()]

    def schedule_session_scrapes(self, session, now):
        # 仅 SPECIAL session 调用该方法。
        self.session_scrape_calls.append(session.session_id)
        return [object(), object()]


class DiscoveryExecutorTestCase(unittest.TestCase):
    def test_discovery_emits_session_scrapes_for_special(self) -> None:
        # SPECIAL session 应自动派发 SESSION_FINAL_SCRAPE，NORMAL 不派发。
        config = replace(AppConfig.from_env())
        adapter = _FakeAdapter()
        session_repo = _FakeSessionRepo()
        scheduler = _FakeScheduler()
        executor = DiscoveryExecutor(config, adapter, session_repo, scheduler)

        task = Task(
            event_type=EventType.DISCOVER_SESSIONS,
            entity_id="hxguquan",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.DISCOVERY,
            payload={"url": "https://www.hxguquan.com/"},
        )
        result = executor.execute(task)

        self.assertTrue(result.success)
        self.assertEqual(2, result.processed_count)
        # 2 个 session 的 discover_lots + 1 个 SPECIAL 的 session_scrapes(2个任务)。
        self.assertEqual(4, result.emitted_task_count)
        self.assertEqual(2, len(session_repo.saved))
        self.assertEqual(["s_special"], scheduler.session_scrape_calls)


if __name__ == "__main__":
    unittest.main()
