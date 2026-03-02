from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ModelSettingsError(ValueError):
    # 配置文件格式非法时抛出，调用方可降级到静态路由。
    pass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class OrchestrationModelSettings:
    enabled: bool
    default_model: str
    fallback_model: str | None
    route_event_types: set[str]
    timeout_seconds: float
    temperature: float
    max_tokens: int
    providers: dict[str, ProviderConfig]
    model_to_provider: dict[str, str]

    def resolve_provider(self, model_name: str) -> ProviderConfig | None:
        provider_name = self.model_to_provider.get(model_name)
        if not provider_name:
            return None
        return self.providers.get(provider_name)


def load_orchestration_model_settings(path: Path) -> OrchestrationModelSettings:
    if not path.exists():
        raise ModelSettingsError(f"模型配置文件不存在: {path}")
    raw = _parse_simple_yaml(path.read_text(encoding="utf-8"))

    runtime = _as_dict(raw.get("runtime"), "runtime")
    routing = _as_dict(raw.get("routing"), "routing")
    request = _as_dict(raw.get("request"), "request")
    providers_node = _as_dict(raw.get("providers"), "providers")
    models_node = _as_dict(raw.get("models"), "models")

    default_model = _as_str(routing.get("default_model"), "routing.default_model")
    fallback_model = _as_optional_str(routing.get("fallback_model"), "routing.fallback_model")
    route_event_types = _parse_route_event_types(routing.get("route_event_types"))

    providers: dict[str, ProviderConfig] = {}
    for provider_name, provider_node in providers_node.items():
        provider_obj = _as_dict(provider_node, f"providers.{provider_name}")
        providers[provider_name] = ProviderConfig(
            name=provider_name,
            base_url=_as_str(provider_obj.get("base_url"), f"providers.{provider_name}.base_url"),
            api_key=_as_str(provider_obj.get("api_key"), f"providers.{provider_name}.api_key"),
        )

    model_to_provider: dict[str, str] = {}
    for model_name, model_node in models_node.items():
        model_obj = _as_dict(model_node, f"models.{model_name}")
        model_to_provider[model_name] = _as_str(model_obj.get("provider"), f"models.{model_name}.provider")

    enabled_value = runtime.get("enable_dynamic_orchestration", True)
    enabled = _as_bool(enabled_value, "runtime.enable_dynamic_orchestration")

    timeout_value = request.get("timeout_seconds", 8)
    temperature_value = request.get("temperature", 0)
    max_tokens_value = request.get("max_tokens", 240)

    settings = OrchestrationModelSettings(
        enabled=enabled,
        default_model=default_model,
        fallback_model=fallback_model,
        route_event_types=route_event_types,
        timeout_seconds=_as_float(timeout_value, "request.timeout_seconds"),
        temperature=_as_float(temperature_value, "request.temperature"),
        max_tokens=_as_int(max_tokens_value, "request.max_tokens"),
        providers=providers,
        model_to_provider=model_to_provider,
    )

    if not settings.resolve_provider(settings.default_model):
        raise ModelSettingsError("default_model 未映射到 provider")
    if settings.fallback_model and not settings.resolve_provider(settings.fallback_model):
        raise ModelSettingsError("fallback_model 未映射到 provider")

    return settings


def _parse_route_event_types(value: object) -> set[str]:
    if value is None:
        return set()
    text = _as_str(value, "routing.route_event_types")
    items = [item.strip() for item in text.split(",") if item.strip()]
    return set(items)


def _parse_simple_yaml(text: str) -> dict[str, object]:
    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        if raw_line.lstrip().startswith("#"):
            continue
        if "\t" in raw_line:
            raise ModelSettingsError(f"不支持 tab 缩进: line {line_no}")

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = _strip_inline_comment(raw_line).rstrip()
        if not line.strip():
            continue

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ModelSettingsError(f"缩进非法: line {line_no}")

        stripped = line.strip()
        if ":" not in stripped:
            raise ModelSettingsError(f"YAML 语法错误（缺少冒号）: line {line_no}")
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise ModelSettingsError(f"YAML 语法错误（空 key）: line {line_no}")

        parent = stack[-1][1]
        value = raw_value.strip()
        if value == "":
            child: dict[str, object] = {}
            parent[key] = child
            stack.append((indent, child))
            continue

        parent[key] = _parse_scalar(value)

    return root


def _strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    out: list[str] = []
    for index, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == "#" and not in_single and not in_double:
            prev = line[index - 1] if index > 0 else " "
            if prev.isspace():
                break
        out.append(ch)
    return "".join(out)


def _parse_scalar(raw: str) -> object:
    if raw in {"true", "True"}:
        return True
    if raw in {"false", "False"}:
        return False
    if raw in {"null", "None", "~"}:
        return None

    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]

    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _as_dict(value: object, field_name: str) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    raise ModelSettingsError(f"{field_name} 必须是对象")


def _as_str(value: object, field_name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ModelSettingsError(f"{field_name} 必须是非空字符串")


def _as_optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    raise ModelSettingsError(f"{field_name} 必须是字符串或 null")


def _as_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ModelSettingsError(f"{field_name} 必须是布尔值")


def _as_float(value: object, field_name: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise ModelSettingsError(f"{field_name} 必须是数字") from exc
    raise ModelSettingsError(f"{field_name} 必须是数字")


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ModelSettingsError(f"{field_name} 必须是整数")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ModelSettingsError(f"{field_name} 必须是整数") from exc
    raise ModelSettingsError(f"{field_name} 必须是整数")
