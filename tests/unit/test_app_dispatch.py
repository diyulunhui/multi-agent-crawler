from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.app import AuctionCrawlerApp
from src.config.settings import AppConfig
from src.domain.events import EventType, Task, TaskPriority
from src.orchestration.dynamic_skill_orchestrator import DispatchTarget


class _FakeOrchestrator:
    def __init__(self, target: DispatchTarget) -> None:
        self.target = target

    def select_dispatch_target(self, task: Task) -> DispatchTarget:
        return self.target


class _FakeExecutor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.called_with: list[str] = []

    def execute(self, task: Task):
        self.called_with.append(task.task_id)
        return {"executor": self.name, "task_id": task.task_id}


class AppDispatchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        cfg = AppConfig.from_env()
        self.config = replace(cfg, db_url="sqlite:///data/test_app_dispatch.db")
        db_path = Path("data/test_app_dispatch.db")
        if db_path.exists():
            db_path.unlink()

    def test_dispatch_should_fallback_to_expected_target_when_llm_target_mismatch(self) -> None:
        app = AuctionCrawlerApp(self.config)
        app.dynamic_orchestrator = _FakeOrchestrator(DispatchTarget.DISCOVERY)  # type: ignore[assignment]
        app.discovery_executor = _FakeExecutor("discovery")  # type: ignore[assignment]
        app.lot_executor = _FakeExecutor("lot")  # type: ignore[assignment]
        app.snapshot_executor = _FakeExecutor("snapshot")  # type: ignore[assignment]

        task = Task(
            event_type=EventType.DISCOVER_LOTS,
            entity_id="s_test",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.DISCOVERY,
            payload={"session_id": "s_test", "url": "https://www.hxguquan.com/goods-list.html?gid=1"},
        )
        result = app.dispatch(task)

        self.assertEqual("lot", result["executor"])
        self.assertEqual([task.task_id], app.lot_executor.called_with)  # type: ignore[attr-defined]
        self.assertEqual([], app.discovery_executor.called_with)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
