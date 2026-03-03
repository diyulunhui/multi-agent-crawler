from __future__ import annotations

import json
import os
import re
import ssl
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.config.settings import AppConfig
from src.domain.events import EventType, Task
from src.orchestration.langgraph_runtime import END, StateGraph
from src.orchestration.model_settings import (
    ModelSettingsError,
    OrchestrationModelSettings,
    ProviderConfig,
    load_orchestration_model_settings,
)


class DispatchTarget(str, Enum):
    # 运行时真正可执行的三个执行器目标。
    # 注意：这里是“内部执行目标”，不是 LLM 看到的 skill 名称。
    # LLM 输出 skill -> 通过 SKILL_TO_TARGET 映射到这里。
    DISCOVERY = "discovery_executor"
    LOT = "lot_executor"
    SNAPSHOT = "snapshot_executor"


@dataclass(frozen=True)
class OrchestrationDecision:
    # 一次编排决策的完整结果，便于后续观测、排障和统计。
    # - skill_name: 模型（或规则回退）最终选中的 skill 名称。
    # - target: 最终映射到哪个执行器。
    # - model_name: 实际使用的模型名；规则回退时为 None。
    # - reason: 模型返回的简短理由，或系统级回退原因。
    # - used_fallback_model: 是否命中了 fallback 模型链路。
    skill_name: str
    target: DispatchTarget
    model_name: str | None
    reason: str | None
    used_fallback_model: bool


# 为了可测试性，把“真正发起模型请求”的行为抽象成函数签名。
# 生产环境默认用 _openai_compatible_chat_completion；
# 单测里可注入 fake 函数，不依赖外网。
ChatCompletionFn = Callable[[ProviderConfig, str, list[dict[str, str]], float, int, float], str]


class _RoutingGraphState(TypedDict, total=False):
    task: Task
    default_target: DispatchTarget
    default_skill: str
    messages: list[dict[str, str]]
    model_chain: list[str]
    decision: OrchestrationDecision


class DynamicSkillOrchestrator:
    """
    动态 Skill 编排器。

    职责分三层：
    1) 把 Task 转成 LLM 可理解的提示词；
    2) 让 LLM 在 skill 集合中做选择（支持默认模型 + fallback 模型）；
    3) 把 skill 安全映射成内部执行器目标（DispatchTarget）。

    设计要点：
    - “LLM 可用但不强依赖”：任何异常都允许回退到静态规则，保证主流程可跑。
    - “白名单路由”：LLM 只能选预定义 skill，杜绝任意字符串导致的执行偏移。
    - “可测试”：网络调用可注入，单测直接模拟模型返回。
    """

    # 模型输出 skill 名称到内部执行目标的白名单映射。
    # 只有这里出现的 skill 才会被接受。
    SKILL_TO_TARGET: dict[str, DispatchTarget] = {
        "hxguquan_discovery_skill": DispatchTarget.DISCOVERY,
        "hxguquan_lot_skill": DispatchTarget.LOT,
        "hxguquan_snapshot_skill": DispatchTarget.SNAPSHOT,
    }

    # 当 LLM 不可用或不启用时，按事件类型走默认目标。
    # 这是系统的“保底路由”。
    EVENT_DEFAULT_TARGET: dict[EventType, DispatchTarget] = {
        EventType.DISCOVER_SESSIONS: DispatchTarget.DISCOVERY,
        EventType.DISCOVER_LOTS: DispatchTarget.LOT,
        EventType.STRUCTURE_LOT: DispatchTarget.LOT,
        EventType.SNAPSHOT_PRE5: DispatchTarget.SNAPSHOT,
        EventType.SNAPSHOT_PRE1: DispatchTarget.SNAPSHOT,
        EventType.SNAPSHOT_FINAL_MONITOR: DispatchTarget.SNAPSHOT,
        EventType.SESSION_FINAL_SCRAPE: DispatchTarget.SNAPSHOT,
    }

    def __init__(
        self,
        config: AppConfig,
        settings_path: Path | None = None,
        chat_completion_fn: ChatCompletionFn | None = None,
    ) -> None:
        # settings_path: 允许测试或特殊部署指定不同配置文件。
        # chat_completion_fn: 允许注入 mock/fake，避免测试依赖网络。
        self.config = config
        self.settings_path = settings_path or config.model_settings_path
        self.chat_completion_fn = chat_completion_fn or _openai_compatible_chat_completion
        # 启动时预加载一次配置。配置无效会降级成 None（即仅走静态路由）。
        self._settings = self._load_settings()
        self._decision_graph = self._build_decision_graph()

    def select_dispatch_target(self, task: Task) -> DispatchTarget:
        # 提供给调用方的简化入口：只关心“最终执行目标”。
        return self.select_decision(task).target

    def select_decision(self, task: Task) -> OrchestrationDecision:
        graph_state: _RoutingGraphState = {"task": task}
        final_state = self._decision_graph.invoke(graph_state)
        decision = final_state.get("decision")
        if isinstance(decision, OrchestrationDecision):
            return decision
        raise RuntimeError("dynamic orchestrator 未产出有效决策。")

    def _build_decision_graph(self):
        graph = StateGraph(_RoutingGraphState)
        graph.add_node("init", self._graph_init_node)
        graph.add_node("llm_route", self._graph_llm_route_node)
        graph.add_node("fallback", self._graph_fallback_node)
        graph.set_entry_point("init")
        graph.add_conditional_edges(
            "init",
            self._graph_init_route,
            {"done": END, "llm": "llm_route"},
        )
        graph.add_conditional_edges(
            "llm_route",
            self._graph_llm_route_route,
            {"done": END, "fallback": "fallback"},
        )
        graph.add_edge("fallback", END)
        return graph.compile()

    def _graph_init_node(self, state: _RoutingGraphState) -> _RoutingGraphState:
        task = state["task"]
        default_target = self._default_target(task.event_type)
        default_skill = self._default_skill(default_target)
        updates: _RoutingGraphState = {
            "default_target": default_target,
            "default_skill": default_skill,
        }

        # 动态编排整体不可用：直接回退。
        if self._settings is None:
            updates["decision"] = OrchestrationDecision(
                skill_name=default_skill,
                target=default_target,
                model_name=None,
                reason="dynamic_orchestration_disabled",
                used_fallback_model=False,
            )
            return updates

        # 支持“按事件范围启用编排”，高频任务可选择只走静态，控制成本/延迟。
        if self._settings.route_event_types and task.event_type.value not in self._settings.route_event_types:
            updates["decision"] = OrchestrationDecision(
                skill_name=default_skill,
                target=default_target,
                model_name=None,
                reason="event_not_in_routing_scope",
                used_fallback_model=False,
            )
            return updates

        # 构造发给模型的上下文，强制限定输出格式为 JSON。
        updates["messages"] = self._build_messages(task, default_skill)
        model_chain = [self._settings.default_model]
        # fallback_model 与 default_model 去重，避免重复调用同一模型。
        if self._settings.fallback_model and self._settings.fallback_model not in model_chain:
            model_chain.append(self._settings.fallback_model)
        updates["model_chain"] = model_chain
        return updates

    @staticmethod
    def _graph_init_route(state: _RoutingGraphState) -> str:
        if isinstance(state.get("decision"), OrchestrationDecision):
            return "done"
        return "llm"

    def _graph_llm_route_node(self, state: _RoutingGraphState) -> _RoutingGraphState:
        if self._settings is None:
            return {}
        messages = state.get("messages") or []
        model_chain = state.get("model_chain") or []
        for index, model_name in enumerate(model_chain):
            provider = self._settings.resolve_provider(model_name)
            # 模型未映射 provider：跳过当前模型。
            if provider is None:
                continue
            try:
                # 第一步：调用模型，拿到原始文本。
                raw_text = self.chat_completion_fn(
                    provider,
                    model_name,
                    messages,
                    self._settings.temperature,
                    self._settings.max_tokens,
                    self._settings.timeout_seconds,
                )
                # 第二步：解析文本为 JSON 对象。
                parsed = self._parse_model_response(raw_text)
                if parsed is None:
                    continue
                # 第三步：把模型输出的 skill（可能有别名）归一化成标准 skill。
                normalized = self._normalize_skill_name(parsed.get("skill"))
                if normalized is None:
                    continue
                # 第四步：白名单映射，防止非法 skill 被执行。
                target = self.SKILL_TO_TARGET.get(normalized)
                if target is None:
                    continue
                # 到这里说明一次模型决策成功，直接返回。
                return {
                    "decision": OrchestrationDecision(
                        skill_name=normalized,
                        target=target,
                        model_name=model_name,
                        reason=self._safe_reason(parsed.get("reason")),
                        used_fallback_model=index > 0,
                    )
                }
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError):
                # 任何模型调用/解析异常都不中断主流程，继续尝试下一个模型。
                continue
        return {}

    @staticmethod
    def _graph_llm_route_route(state: _RoutingGraphState) -> str:
        if isinstance(state.get("decision"), OrchestrationDecision):
            return "done"
        return "fallback"

    def _graph_fallback_node(self, state: _RoutingGraphState) -> _RoutingGraphState:
        default_target = state["default_target"]
        default_skill = state["default_skill"]
        # 所有模型都失败时，回退到静态规则路由。
        return {
            "decision": OrchestrationDecision(
                skill_name=default_skill,
                target=default_target,
                model_name=None,
                reason="llm_failed_use_rule_fallback",
                used_fallback_model=False,
            )
        }

    def _load_settings(self) -> OrchestrationModelSettings | None:
        # 开关层：环境变量可全局关闭动态编排。
        if not self.config.enable_dynamic_orchestration:
            return None
        try:
            settings = load_orchestration_model_settings(self.settings_path)
        except ModelSettingsError:
            # 配置解析失败不抛出到上层，直接降级静态路由。
            return None
        # 配置文件内部也有一个开关，便于按文件控制。
        if not settings.enabled:
            return None
        return settings

    @classmethod
    def _default_target(cls, event_type: EventType) -> DispatchTarget:
        # 统一读取事件类型对应的静态保底目标。
        target = cls.EVENT_DEFAULT_TARGET.get(event_type)
        if target is None:
            raise ValueError(f"未支持的任务类型: {event_type}")
        return target

    @classmethod
    def _default_skill(cls, target: DispatchTarget) -> str:
        # 反向查找“目标执行器”对应的默认 skill 名称。
        for skill_name, mapped_target in cls.SKILL_TO_TARGET.items():
            if mapped_target == target:
                return skill_name
        raise ValueError(f"未找到 target 对应 skill: {target}")

    @classmethod
    def _build_messages(cls, task: Task, default_skill: str) -> list[dict[str, str]]:
        # system_prompt 只描述“规则边界”，避免模型输出跑偏。
        system_prompt = (
            "你是拍卖抓取系统的调度编排器。"
            "你只能在以下 skill 中选择一个："
            "hxguquan_discovery_skill, hxguquan_lot_skill, hxguquan_snapshot_skill。"
            "必须输出严格 JSON，不要输出 markdown。"
            "输出格式: "
            '{"skill":"<skill_name>","reason":"<short_reason>"}'
        )

        task_payload = {
            "task_id": task.task_id,
            "event_type": task.event_type.value,
            "entity_id": task.entity_id,
            "run_at": task.run_at.isoformat(),
            "priority": int(task.priority),
            "payload": task.payload,
            "default_skill": default_skill,
        }
        # user_prompt 提供任务完整上下文，并给出“信息不足时回 default_skill”的兜底指令。
        user_prompt = (
            "请根据任务信息选出一个最合适的 skill。"
            "如果信息不足，优先返回 default_skill。"
            f"\n任务信息: {json.dumps(task_payload, ensure_ascii=False, sort_keys=True)}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _parse_model_response(text: str) -> dict[str, object] | None:
        # 优先按“纯 JSON”解析（最理想情况）。
        cleaned = text.strip()
        if not cleaned:
            return None
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # 兼容模型返回“解释 + JSON”的情况：尝试提取首个 {...} 片段再解析。
        # 注意：这是宽松解析策略，依然会在后续做 skill 白名单约束。
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    @classmethod
    def _normalize_skill_name(cls, value: object) -> str | None:
        # 模型可能输出别名，这里统一归一化，减少提示词抖动带来的失败率。
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        alias_map = {
            "hxguquan_discovery_skill": "hxguquan_discovery_skill",
            "discovery": "hxguquan_discovery_skill",
            "discovery_skill": "hxguquan_discovery_skill",
            "hxguquan_lot_skill": "hxguquan_lot_skill",
            "lot": "hxguquan_lot_skill",
            "lot_skill": "hxguquan_lot_skill",
            "hxguquan_snapshot_skill": "hxguquan_snapshot_skill",
            "snapshot": "hxguquan_snapshot_skill",
            "snapshot_skill": "hxguquan_snapshot_skill",
        }
        return alias_map.get(normalized)

    @staticmethod
    def _safe_reason(reason_value: object) -> str | None:
        # reason 仅作为观测信息，不参与执行逻辑；这里做类型和空值清洗。
        if isinstance(reason_value, str):
            reason = reason_value.strip()
            return reason or None
        return None


def _openai_compatible_chat_completion(
    provider: ProviderConfig,
    model_name: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout_seconds: float,
) -> str:
    """
    使用 OpenAI 兼容协议调用 Chat Completions。

    这里不依赖第三方 SDK，直接用 urllib，原因：
    - 降低依赖；
    - 便于在受限环境运行；
    - 统一兼容 siliconflow / deepseek 这类 OpenAI 风格接口。
    """
    endpoint = provider.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # 认证使用 Bearer Token。
    request = Request(
        url=endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
        },
        method="POST",
    )
    # 网络层超时由 timeout_seconds 控制，超时会抛异常，由上层决定是否回退。
    insecure_tls = os.getenv("OPENAI_COMPAT_INSECURE_TLS", "").strip().lower() in {"1", "true", "yes"}
    ssl_context = ssl._create_unverified_context() if insecure_tls else None
    try:
        with urlopen(request, timeout=timeout_seconds, context=ssl_context) as response:
            response_text = response.read().decode("utf-8")
    except URLError as exc:
        # 默认先走安全证书校验；仅当本机证书链问题导致校验失败时，自动降级重试一次。
        if not insecure_tls and _is_certificate_verify_error(exc):
            with urlopen(request, timeout=timeout_seconds, context=ssl._create_unverified_context()) as response:
                response_text = response.read().decode("utf-8")
        else:
            raise

    # 按 OpenAI 兼容格式提取 choices[0].message.content。
    parsed = json.loads(response_text)
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM 响应缺少 choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("LLM 响应 choices[0] 非法")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("LLM 响应缺少 message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM message.content 为空")
    return content


def _is_certificate_verify_error(exc: URLError) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    text = str(reason if reason is not None else exc)
    lowered = text.lower()
    return "certificate verify failed" in lowered or "certificate_verify_failed" in lowered
