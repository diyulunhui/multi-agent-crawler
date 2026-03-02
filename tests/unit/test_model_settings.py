from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.orchestration.model_settings import ModelSettingsError, load_orchestration_model_settings


class ModelSettingsLoaderTestCase(unittest.TestCase):
    def _write_temp_yaml(self, content: str) -> Path:
        temp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        temp.write(content)
        temp.flush()
        temp.close()
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        return Path(temp.name)

    def test_load_model_settings_success(self) -> None:
        # 应正确加载 default/fallback/provider/model 映射关系。
        path = self._write_temp_yaml(
            """
runtime:
  enable_dynamic_orchestration: true
routing:
  default_model: moonshotai/Kimi-K2-Instruct
  fallback_model: deepseek-chat
  route_event_types: DISCOVER_SESSIONS,DISCOVER_LOTS
request:
  timeout_seconds: 9
  temperature: 0
  max_tokens: 128
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

        settings = load_orchestration_model_settings(path)
        self.assertTrue(settings.enabled)
        self.assertEqual("moonshotai/Kimi-K2-Instruct", settings.default_model)
        self.assertEqual("deepseek-chat", settings.fallback_model)
        self.assertEqual({"DISCOVER_SESSIONS", "DISCOVER_LOTS"}, settings.route_event_types)
        self.assertEqual(9.0, settings.timeout_seconds)
        self.assertEqual(0.0, settings.temperature)
        self.assertEqual(128, settings.max_tokens)
        self.assertEqual("siliconflow", settings.model_to_provider["moonshotai/Kimi-K2-Instruct"])
        self.assertEqual("deepseek", settings.model_to_provider["deepseek-chat"])

    def test_load_model_settings_raises_when_default_model_not_mapped(self) -> None:
        # default_model 未配置 provider 时应抛出配置异常。
        path = self._write_temp_yaml(
            """
runtime:
  enable_dynamic_orchestration: true
routing:
  default_model: moonshotai/Kimi-K2-Instruct
request:
  timeout_seconds: 8
  temperature: 0
  max_tokens: 64
providers:
  siliconflow:
    base_url: https://api.siliconflow.cn/v1
    api_key: sf_key
models:
  deepseek-chat:
    provider: siliconflow
"""
        )

        with self.assertRaises(ModelSettingsError):
            load_orchestration_model_settings(path)


if __name__ == "__main__":
    unittest.main()
