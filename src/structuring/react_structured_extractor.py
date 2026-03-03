from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, TypedDict
from urllib.error import HTTPError, URLError

from src.orchestration.langgraph_runtime import END, StateGraph
from src.orchestration.model_settings import OrchestrationModelSettings, ProviderConfig
from src.scraping.normalizers import clean_text


ChatCompletionFn = Callable[[ProviderConfig, str, list[dict[str, str]], float, int, float], str]
ParseModelResponseFn = Callable[[str], dict[str, object] | None]
NormalizePayloadFn = Callable[[dict[str, object], str, str, list[str]], dict[str, object] | None]
RuleExtractFn = Callable[[str, list[str], str], dict[str, object]]


@dataclass(frozen=True)
class ReactExtractionOutput:
    normalized_payload: dict[str, object]
    trace_hits: list[str]
    model_name: str


class _ReactGraphState(TypedDict, total=False):
    title: str
    description: str
    labels: list[str]
    merged_text: str
    rule_hint: dict[str, object]
    messages: list[dict[str, str]]
    trace_hits: list[str]
    step: int
    status: str
    output: ReactExtractionOutput


class ReactStructuredExtractor:
    # ReAct 白名单工具：仅允许有限本地读工具，不允许任意执行。
    ALLOWED_ACTIONS = {"find_keyword", "regex_extract", "rule_extract"}

    def __init__(
        self,
        settings: OrchestrationModelSettings,
        chat_completion_fn: ChatCompletionFn,
        parse_model_response_fn: ParseModelResponseFn,
        normalize_payload_fn: NormalizePayloadFn,
        rule_extract_fn: RuleExtractFn,
        max_steps: int = 3,
    ) -> None:
        self.settings = settings
        self.chat_completion_fn = chat_completion_fn
        self.parse_model_response_fn = parse_model_response_fn
        self.normalize_payload_fn = normalize_payload_fn
        self.rule_extract_fn = rule_extract_fn
        self.max_steps = max(1, min(max_steps, 5))
        self._graph = self._build_graph()

    def extract(
        self,
        lot_id: str,
        title: str,
        description: str,
        labels: list[str],
        category_hint: str,
        base_payload: dict[str, object],
    ) -> ReactExtractionOutput | None:
        merged_text = clean_text(" ".join([title, description, " ".join(labels), category_hint]))
        rule_hint = self.rule_extract_fn(merged_text, labels, category_hint)
        messages = self._build_messages(
            lot_id=lot_id,
            title=title,
            description=description,
            labels=labels,
            category_hint=category_hint,
            base_payload=base_payload,
            rule_hint=rule_hint,
        )
        state: _ReactGraphState = {
            "title": title,
            "description": description,
            "labels": labels,
            "merged_text": merged_text,
            "rule_hint": rule_hint,
            "messages": messages,
            "trace_hits": [],
            "step": 0,
            "status": "loop",
        }
        final_state = self._graph.invoke(state)
        output = final_state.get("output")
        return output if isinstance(output, ReactExtractionOutput) else None

    def _build_graph(self):
        graph = StateGraph(_ReactGraphState)
        graph.add_node("react_step", self._graph_react_step)
        graph.set_entry_point("react_step")
        graph.add_conditional_edges(
            "react_step",
            self._graph_route,
            {"loop": "react_step", "done": END},
        )
        return graph.compile()

    @staticmethod
    def _graph_route(state: _ReactGraphState) -> str:
        status = str(state.get("status") or "")
        if status in {"done", "fail", "exceeded"}:
            return "done"
        return "loop"

    def _graph_react_step(self, state: _ReactGraphState) -> _ReactGraphState:
        step = int(state.get("step", 0))
        if step >= self.max_steps:
            return {"status": "exceeded"}

        title = str(state.get("title") or "")
        description = str(state.get("description") or "")
        labels = state.get("labels") or []
        messages = state.get("messages") or []
        merged_text = str(state.get("merged_text") or "")
        rule_hint = state.get("rule_hint") or {}
        trace_hits = list(state.get("trace_hits") or [])
        step_index = step + 1

        model_reply = self._call_model_chain(messages)
        if model_reply is None:
            return {"step": step_index, "status": "fail"}

        model_name, raw_text = model_reply
        parsed = self.parse_model_response_fn(raw_text)
        if parsed is None:
            return {
                "messages": messages
                + [
                    {
                        "role": "user",
                        "content": "输出解析失败，请仅返回严格 JSON，继续 action 或 final。",
                    }
                ],
                "trace_hits": trace_hits,
                "step": step_index,
                "status": "loop",
            }

        node_type = str(parsed.get("type") or "").strip().lower()
        if node_type == "final":
            result_node = parsed.get("result")
            if not isinstance(result_node, dict):
                return {
                    "messages": messages + [{"role": "user", "content": "final.result 非法，请补全后重试。"}],
                    "trace_hits": trace_hits,
                    "step": step_index,
                    "status": "loop",
                }
            normalized = self.normalize_payload_fn(result_node, title, description, labels)
            if normalized is None:
                return {
                    "messages": messages
                    + [
                        {
                            "role": "user",
                            "content": "final.result 字段不可用，请结合证据修正后再输出。",
                        }
                    ],
                    "trace_hits": trace_hits,
                    "step": step_index,
                    "status": "loop",
                }
            return {
                "output": ReactExtractionOutput(
                    normalized_payload=normalized,
                    trace_hits=trace_hits[:8],
                    model_name=model_name,
                ),
                "step": step_index,
                "status": "done",
            }

        action = str(parsed.get("action") or "").strip()
        args = parsed.get("args")
        if node_type != "action" or action not in self.ALLOWED_ACTIONS or not isinstance(args, dict):
            return {
                "messages": messages
                + [
                    {
                        "role": "user",
                        "content": "仅允许 action=find_keyword/regex_extract/rule_extract 或 final。",
                    }
                ],
                "trace_hits": trace_hits,
                "step": step_index,
                "status": "loop",
            }

        observation, trace_hit = self._run_action(action=action, args=args, merged_text=merged_text, rule_hint=rule_hint)
        if trace_hit is not None and trace_hit not in trace_hits:
            trace_hits.append(trace_hit)
        return {
            "messages": messages
            + [{"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False, sort_keys=True)}]
            + [
                {
                    "role": "user",
                    "content": f"工具观察#{step_index}: {observation}。请继续下一步，或输出 final。",
                }
            ],
            "trace_hits": trace_hits,
            "step": step_index,
            "status": "loop",
        }

    def _call_model_chain(self, messages: list[dict[str, str]]) -> tuple[str, str] | None:
        model_chain = [self.settings.default_model]
        if self.settings.fallback_model and self.settings.fallback_model not in model_chain:
            model_chain.append(self.settings.fallback_model)

        for model_name in model_chain:
            provider = self.settings.resolve_provider(model_name)
            if provider is None:
                continue
            try:
                text = self.chat_completion_fn(
                    provider=provider,
                    model_name=model_name,
                    messages=messages,
                    temperature=self.settings.temperature,
                    max_tokens=self.settings.max_tokens,
                    timeout_seconds=self.settings.timeout_seconds,
                )
                return model_name, text
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError):
                continue
        return None

    @staticmethod
    def _build_messages(
        lot_id: str,
        title: str,
        description: str,
        labels: list[str],
        category_hint: str,
        base_payload: dict[str, object],
        rule_hint: dict[str, object],
    ) -> list[dict[str, str]]:
        system_prompt = (
            "你是拍品结构化 ReAct 抽取器。"
            "每一步必须输出严格 JSON，不要输出 markdown。"
            "你有三种 action：find_keyword、regex_extract、rule_extract。"
            "当证据足够时输出 final。"
            "action 格式："
            '{"type":"action","action":"find_keyword|regex_extract|rule_extract","args":{...}}。'
            "final 格式："
            '{"type":"final","result":{"coin_type":null|"...","variety":null|"...","mint_year":null|"...",'
            '"grading_company":null|"...","grade_score":null|"...","denomination":null|"...","special_tags":[]},'
            '"reason":"..."}。'
            "不能凭空编造，无法确认请返回 null。"
        )
        payload = {
            "lot_id": lot_id,
            "title": title,
            "description": description,
            "labels": labels,
            "category_hint": category_hint,
            "base_candidate": base_payload,
            "rule_hint": rule_hint,
        }
        user_prompt = (
            "先 action 取证，再 final 输出字段。"
            f"\n输入: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    @staticmethod
    def _run_action(
        action: str,
        args: dict[str, object],
        merged_text: str,
        rule_hint: dict[str, object],
    ) -> tuple[str, str | None]:
        if action == "find_keyword":
            keyword = clean_text(str(args.get("keyword") or ""))
            if not keyword:
                return "keyword 为空", None
            count = merged_text.count(keyword)
            found = count > 0
            return (
                json.dumps({"keyword": keyword, "found": found, "count": count}, ensure_ascii=False),
                f"react_tool:find_keyword:{keyword}:{count}",
            )

        if action == "regex_extract":
            pattern = clean_text(str(args.get("pattern") or ""))
            if not pattern or len(pattern) > 120:
                return "pattern 非法", None
            try:
                matches = re.findall(pattern, merged_text)
            except re.error:
                return "pattern 编译失败", None
            normalized_matches = [str(item) for item in matches[:8]]
            return (
                json.dumps({"pattern": pattern, "matches": normalized_matches}, ensure_ascii=False),
                "react_tool:regex_extract",
            )

        if action == "rule_extract":
            return json.dumps(rule_hint, ensure_ascii=False, sort_keys=True), "react_tool:rule_extract"

        return "action 不支持", None
