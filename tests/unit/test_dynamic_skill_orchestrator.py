from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import AppConfig
from src.domain.events import EventType, Task, TaskPriority
from src.orchestration.dynamic_skill_orchestrator import DispatchTarget, DynamicSkillOrchestrator
from src.orchestration.model_settings import ProviderConfig


class DynamicSkillOrchestratorTestCase(unittest.TestCase):
    def _write_temp_yaml(self, content: str) -> Path:
        temp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        temp.write(content)
        temp.flush()
        temp.close()
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        return Path(temp.name)

    def _base_config(self) -> AppConfig:
        cfg = AppConfig.from_env()
        return replace(cfg, enable_dynamic_orchestration=True)

    def _build_task(self, event_type: EventType) -> Task:
        return Task(
            event_type=event_type,
            entity_id="entity-1",
            run_at=datetime.now(timezone.utc),
            priority=TaskPriority.DISCOVERY,
            payload={"url": "https://www.hxguquan.com/"},
        )

    def test_use_rule_fallback_when_disabled(self) -> None:
        # 动态编排关闭时，应直接走静态默认路由。
        cfg = replace(self._base_config(), enable_dynamic_orchestration=False)
        orchestrator = DynamicSkillOrchestrator(cfg, settings_path=Path("not_exists.yaml"))
        task = self._build_task(EventType.DISCOVER_SESSIONS)
        self.assertEqual(DispatchTarget.DISCOVERY, orchestrator.select_dispatch_target(task))

    def test_llm_route_success(self) -> None:
        # 大模型返回 lot skill 时，应映射到 LOT 执行器。
        settings_path = self._write_temp_yaml(
            """
runtime:
  enable_dynamic_orchestration: true
routing:
  default_model: moonshotai/Kimi-K2-Instruct
  fallback_model: deepseek-chat
  route_event_types: DISCOVER_LOTS
request:
  timeout_seconds: 5
  temperature: 0
  max_tokens: 120
providers:
  siliconflow:
    base_url: https://api.siliconflow.cn/v1
    api_key: sf_key
  deepseek:
    base_url: https://api.deepseek.com/v1
    api_key: ds_key
models:
  moonshotai/Kimi-K2-Instruct:
    provider: siliconflow
  deepseek-chat:
    provider: deepseek
"""
        )
        cfg = replace(self._base_config(), model_settings_path=settings_path)

        def fake_chat(
            provider: ProviderConfig,
            model_name: str,
            messages,
            temperature: float,
            max_tokens: int,
            timeout_seconds: float,
        ) -> str:
            self.assertEqual("moonshotai/Kimi-K2-Instruct", model_name)
            self.assertEqual("siliconflow", provider.name)
            return '{"skill":"hxguquan_lot_skill","reason":"event_type是DISCOVER_LOTS"}'

        orchestrator = DynamicSkillOrchestrator(cfg, chat_completion_fn=fake_chat)
        task = self._build_task(EventType.DISCOVER_LOTS)
        decision = orchestrator.select_decision(task)
        self.assertEqual("hxguquan_lot_skill", decision.skill_name)
        self.assertEqual(DispatchTarget.LOT, decision.target)
        self.assertEqual("moonshotai/Kimi-K2-Instruct", decision.model_name)
        self.assertFalse(decision.used_fallback_model)

    def test_fallback_model_when_primary_fails(self) -> None:
        # 默认模型失败时应自动切到 fallback 模型继续编排。
        settings_path = self._write_temp_yaml(
            """
runtime:
  enable_dynamic_orchestration: true
routing:
  default_model: moonshotai/Kimi-K2-Instruct
  fallback_model: deepseek-chat
  route_event_types: DISCOVER_SESSIONS
request:
  timeout_seconds: 5
  temperature: 0
  max_tokens: 120
providers:
  siliconflow:
    base_url: https://api.siliconflow.cn/v1
    api_key: sf_key
  deepseek:
    base_url: https://api.deepseek.com/v1
    api_key: ds_key
models:
  moonshotai/Kimi-K2-Instruct:
    provider: siliconflow
  deepseek-chat:
    provider: deepseek
"""
        )
        cfg = replace(self._base_config(), model_settings_path=settings_path)
        call_order: list[str] = []

        def fake_chat(
            provider: ProviderConfig,
            model_name: str,
            messages,
            temperature: float,
            max_tokens: int,
            timeout_seconds: float,
        ) -> str:
            call_order.append(model_name)
            if model_name == "moonshotai/Kimi-K2-Instruct":
                raise TimeoutError("primary timeout")
            return '{"skill":"hxguquan_discovery_skill","reason":"fallback success"}'

        orchestrator = DynamicSkillOrchestrator(cfg, chat_completion_fn=fake_chat)
        task = self._build_task(EventType.DISCOVER_SESSIONS)
        decision = orchestrator.select_decision(task)

        self.assertEqual(["moonshotai/Kimi-K2-Instruct", "deepseek-chat"], call_order)
        self.assertEqual(DispatchTarget.DISCOVERY, decision.target)
        self.assertEqual("deepseek-chat", decision.model_name)
        self.assertTrue(decision.used_fallback_model)


if __name__ == "__main__":
    unittest.main()
