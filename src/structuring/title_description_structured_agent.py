from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError

from src.orchestration.dynamic_skill_orchestrator import _openai_compatible_chat_completion
from src.orchestration.model_settings import (
    ModelSettingsError,
    OrchestrationModelSettings,
    ProviderConfig,
    load_orchestration_model_settings,
)
from src.structuring.react_structured_extractor import ReactStructuredExtractor
from src.scraping.normalizers import clean_text


@dataclass(frozen=True)
class StructuredCleaningResult:
    # 结构化清洗结果：核心字段 + 置信度 + 复核标记。
    lot_id: str
    coin_type: str | None
    variety: str | None
    mint_year: str | None
    grading_company: str | None
    grade_score: str | None
    denomination: str | None
    special_tags: list[str]
    confidence_score: Decimal
    extract_source: str
    schema_version: str
    fallback_used: bool
    needs_manual_review: bool
    review_reason: str | None
    raw_payload_json: str

    def to_payload(self) -> dict[str, object]:
        # 输出和 raw_payload_json 保持一致结构，供复核和调试使用。
        return json.loads(self.raw_payload_json)


@dataclass(frozen=True)
class _Candidate:
    # 单轮规则抽取候选结果。
    coin_type: str | None
    variety: str | None
    mint_year: str | None
    grading_company: str | None
    grade_score: str | None
    denomination: str | None
    special_tags: list[str]
    rule_hits: list[str]
    extract_source: str

    def core_field_count(self) -> int:
        # 统计核心字段命中数，用于比较主规则与回退规则结果质量。
        fields = [
            self.coin_type,
            self.variety,
            self.mint_year,
            self.grading_company,
            self.grade_score,
            self.denomination,
        ]
        return sum(1 for value in fields if value)


# 为了可测试性，把“真正发起模型请求”的行为抽象成函数签名。
ChatCompletionFn = Callable[[ProviderConfig, str, list[dict[str, str]], float, int, float], str]


class TitleDescriptionStructuredAgent:
    # 结构化清洗智能体版本号，便于后续回放与对比规则效果。
    VERSION = "structured-react-v1"
    LOW_CONFIDENCE_THRESHOLD = Decimal("0.68")
    LLM_EXTRACT_SOURCE = "llm_structured"
    LLM_WITH_RULE_FILL_SOURCE = "llm_structured_with_rule_fill"
    LLM_FUSION_SOURCE = "llm_fusion"
    LLM_FUSION_WITH_RULE_FILL_SOURCE = "llm_fusion_with_rule_fill"
    REACT_EXTRACT_SOURCE = "react_structured"
    REACT_WITH_RULE_FILL_SOURCE = "react_structured_with_rule_fill"

    # JSON Schema：约束清洗输出结构，防止异常字段写库污染。
    OUTPUT_JSON_SCHEMA: dict[str, object] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "lot_id",
            "coin_type",
            "variety",
            "mint_year",
            "grading_company",
            "grade_score",
            "denomination",
            "special_tags",
            "rule_hits",
            "confidence_score",
            "extract_source",
            "schema_version",
            "fallback_used",
            "needs_manual_review",
            "review_reason",
        ],
        "properties": {
            "lot_id": {"type": "string", "minLength": 1},
            "coin_type": {"type": ["string", "null"]},
            "variety": {"type": ["string", "null"]},
            "mint_year": {"type": ["string", "null"]},
            "grading_company": {"type": ["string", "null"]},
            "grade_score": {"type": ["string", "null"]},
            "denomination": {"type": ["string", "null"]},
            "special_tags": {"type": "array", "items": {"type": "string"}},
            "rule_hits": {"type": "array", "items": {"type": "string"}},
            "confidence_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "extract_source": {
                "type": "string",
                "enum": [
                    "title_rules",
                    "fallback_rules",
                    "llm_structured",
                    "llm_structured_with_rule_fill",
                    "llm_fusion",
                    "llm_fusion_with_rule_fill",
                    "react_structured",
                    "react_structured_with_rule_fill",
                    "schema_fallback",
                ],
            },
            "schema_version": {"type": "string", "minLength": 1},
            "fallback_used": {"type": "boolean"},
            "needs_manual_review": {"type": "boolean"},
            "review_reason": {"type": ["string", "null"]},
        },
    }

    def __init__(
        self,
        enable_llm: bool = False,
        settings_path: Path | None = None,
        chat_completion_fn: ChatCompletionFn | None = None,
        enable_react: bool = False,
        react_max_steps: int = 3,
    ) -> None:
        # 默认关闭 LLM，避免单测依赖外网；生产环境在装配层显式开启。
        self.enable_llm = enable_llm
        self.settings_path = settings_path or Path("model_settings.yaml")
        self.chat_completion_fn = chat_completion_fn or _openai_compatible_chat_completion
        self._settings = self._load_settings() if enable_llm else None
        self.enable_react = enable_react
        self.react_max_steps = max(1, min(react_max_steps, 5))
        # 网络失败时做短暂退避，避免瞬时故障导致长期完全回退规则。
        self._llm_backoff_until = 0.0
        self._llm_network_failures = 0
        self._react_extractor = self._build_react_extractor()

    def clean(
        self,
        lot_id: str,
        title: str,
        description: str | None,
        labels_json: str | None = None,
        category_hint: str | None = None,
        use_react: bool = False,
    ) -> StructuredCleaningResult:
        # 主流程：先跑主规则，再跑回退规则，最后执行 schema 校验和复核判定。
        lot_id_text = clean_text(lot_id)
        title_text = clean_text(title)
        desc_text = clean_text(description)
        labels = self._parse_labels(labels_json)
        hint_text = clean_text(category_hint)

        primary_candidate = self._extract_candidate(
            text=title_text,
            labels=labels,
            category_hint=hint_text,
            source="title_rules",
        )
        primary_score = self._score_candidate(primary_candidate, prefer_title=True, fallback_used=False)

        merged_text = clean_text(" ".join(part for part in [title_text, desc_text, " ".join(labels), hint_text] if part))
        fallback_candidate = self._extract_candidate(
            text=merged_text,
            labels=labels,
            category_hint=hint_text,
            source="fallback_rules",
        )
        fallback_score = self._score_candidate(fallback_candidate, prefer_title=False, fallback_used=True)

        selected = primary_candidate
        selected_score = primary_score
        fallback_used = False
        # 回退策略：字段更全或置信度显著更高时，采用回退结果。
        if fallback_candidate.core_field_count() > primary_candidate.core_field_count() or (
            fallback_score >= primary_score + Decimal("0.05")
        ):
            selected = fallback_candidate
            selected_score = fallback_score
            fallback_used = True

        rule_verified_candidate = selected
        llm_candidate = self._extract_candidate_by_llm(
            lot_id=lot_id_text or "unknown_lot",
            title=title_text,
            description=desc_text,
            labels=labels,
            category_hint=hint_text,
        )
        # 默认走 LLM 主提取，规则用于校验与补全。
        if llm_candidate is not None:
            llm_with_rule_fill = self._merge_candidates(
                preferred=llm_candidate,
                fallback=rule_verified_candidate,
                merged_source=self.LLM_WITH_RULE_FILL_SOURCE,
            )
            conflict_fields = self._detect_candidate_conflicts(
                llm_candidate=llm_candidate,
                rule_candidate=rule_verified_candidate,
            )
            selected = llm_with_rule_fill
            if conflict_fields:
                fused_candidate = self._extract_candidate_by_llm_fusion(
                    lot_id=lot_id_text or "unknown_lot",
                    title=title_text,
                    description=desc_text,
                    labels=labels,
                    category_hint=hint_text,
                    llm_candidate=llm_candidate,
                    rule_candidate=rule_verified_candidate,
                    conflict_fields=conflict_fields,
                )
                if fused_candidate is not None:
                    selected = self._merge_candidates(
                        preferred=fused_candidate,
                        fallback=llm_with_rule_fill,
                        merged_source=self.LLM_FUSION_WITH_RULE_FILL_SOURCE,
                    )
                    selected = self._append_rule_hits(
                        selected,
                        [f"llm_fusion_conflict:{field}" for field in conflict_fields],
                    )
            selected_score = self._score_candidate(selected, prefer_title=True, fallback_used=False)
            fallback_used = False

        if use_react and self._should_trigger_react(selected, selected_score):
            react_candidate = self._extract_candidate_by_react(
                lot_id=lot_id_text or "unknown_lot",
                title=title_text,
                description=desc_text,
                labels=labels,
                category_hint=hint_text,
                base_candidate=selected,
            )
            if react_candidate is not None:
                selected = self._merge_candidates(
                    preferred=react_candidate,
                    fallback=selected,
                    merged_source=self.REACT_WITH_RULE_FILL_SOURCE,
                )
                selected_score = self._score_candidate(selected, prefer_title=True, fallback_used=False)
                fallback_used = False

        review_reason = self._build_review_reason(selected_score, selected)
        payload = {
            "lot_id": lot_id_text or "unknown_lot",
            "coin_type": selected.coin_type,
            "variety": selected.variety,
            "mint_year": selected.mint_year,
            "grading_company": selected.grading_company,
            "grade_score": selected.grade_score,
            "denomination": selected.denomination,
            "special_tags": selected.special_tags,
            "rule_hits": selected.rule_hits,
            "confidence_score": float(selected_score),
            "extract_source": selected.extract_source,
            "schema_version": self.VERSION,
            "fallback_used": fallback_used,
            "needs_manual_review": review_reason is not None,
            "review_reason": review_reason,
        }

        validation_error = self._validate_payload(payload)
        if validation_error is not None:
            # schema 校验失败时强制回退到安全输出，避免脏结构写库。
            payload = self._schema_fallback_payload(lot_id_text or "unknown_lot", validation_error)

        return StructuredCleaningResult(
            lot_id=str(payload["lot_id"]),
            coin_type=payload["coin_type"] if isinstance(payload["coin_type"], str) else None,
            variety=payload["variety"] if isinstance(payload["variety"], str) else None,
            mint_year=payload["mint_year"] if isinstance(payload["mint_year"], str) else None,
            grading_company=payload["grading_company"] if isinstance(payload["grading_company"], str) else None,
            grade_score=payload["grade_score"] if isinstance(payload["grade_score"], str) else None,
            denomination=payload["denomination"] if isinstance(payload["denomination"], str) else None,
            special_tags=[str(tag) for tag in payload["special_tags"]] if isinstance(payload["special_tags"], list) else [],
            confidence_score=Decimal(str(payload["confidence_score"])).quantize(Decimal("0.01")),
            extract_source=str(payload["extract_source"]),
            schema_version=str(payload["schema_version"]),
            fallback_used=bool(payload["fallback_used"]),
            needs_manual_review=bool(payload["needs_manual_review"]),
            review_reason=payload["review_reason"] if isinstance(payload["review_reason"], str) else None,
            raw_payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    def _load_settings(self) -> OrchestrationModelSettings | None:
        try:
            settings = load_orchestration_model_settings(self.settings_path)
        except ModelSettingsError:
            return None
        if not settings.enabled:
            return None
        return settings

    def _build_react_extractor(self) -> ReactStructuredExtractor | None:
        if not self.enable_react or self._settings is None:
            return None
        return ReactStructuredExtractor(
            settings=self._settings,
            chat_completion_fn=self.chat_completion_fn,
            parse_model_response_fn=self._parse_model_response,
            normalize_payload_fn=lambda payload, title, description, labels: self._normalize_model_payload(
                payload=payload,
                title=title,
                description=description,
                labels=labels,
                source_tag="react",
            ),
            rule_extract_fn=self._build_rule_hint_for_react,
            max_steps=self.react_max_steps,
        )

    @classmethod
    def _should_trigger_react(cls, candidate: _Candidate, score: Decimal) -> bool:
        # ReAct 只用于疑难样本：低置信度、核心字段不足或关键字段冲突。
        if score < cls.LOW_CONFIDENCE_THRESHOLD:
            return True
        if candidate.core_field_count() <= 2:
            return True
        if candidate.grade_score and candidate.grading_company is None:
            return True
        conflict_hits = [hit for hit in candidate.rule_hits if hit.startswith("llm_fusion_conflict:")]
        if len(conflict_hits) >= 2:
            return True
        return False

    def _extract_candidate_by_react(
        self,
        lot_id: str,
        title: str,
        description: str,
        labels: list[str],
        category_hint: str,
        base_candidate: _Candidate,
    ) -> _Candidate | None:
        if self._react_extractor is None:
            return None
        result = self._react_extractor.extract(
            lot_id=lot_id,
            title=title,
            description=description,
            labels=labels,
            category_hint=category_hint,
            base_payload=self._candidate_to_payload(base_candidate),
        )
        if result is None:
            return None
        candidate = self._candidate_from_normalized_payload(
            normalized=result.normalized_payload,
            source=self.REACT_EXTRACT_SOURCE,
        )
        if candidate is None:
            return None
        merged_hits = list(candidate.rule_hits)
        for hit in result.trace_hits:
            if hit and hit not in merged_hits:
                merged_hits.append(hit)
        return _Candidate(
            coin_type=candidate.coin_type,
            variety=candidate.variety,
            mint_year=candidate.mint_year,
            grading_company=candidate.grading_company,
            grade_score=candidate.grade_score,
            denomination=candidate.denomination,
            special_tags=candidate.special_tags,
            rule_hits=merged_hits,
            extract_source=candidate.extract_source,
        )

    @staticmethod
    def _candidate_to_payload(candidate: _Candidate) -> dict[str, object]:
        return {
            "coin_type": candidate.coin_type,
            "variety": candidate.variety,
            "mint_year": candidate.mint_year,
            "grading_company": candidate.grading_company,
            "grade_score": candidate.grade_score,
            "denomination": candidate.denomination,
            "special_tags": candidate.special_tags,
            "rule_hits": candidate.rule_hits,
            "extract_source": candidate.extract_source,
        }

    def _build_rule_hint_for_react(self, text: str, labels: list[str], category_hint: str) -> dict[str, object]:
        candidate = self._extract_candidate(text=text, labels=labels, category_hint=category_hint, source="react_rule_hint")
        return self._candidate_to_payload(candidate)

    @staticmethod
    def _build_llm_messages(
        lot_id: str,
        title: str,
        description: str,
        labels: list[str],
        category_hint: str,
    ) -> list[dict[str, str]]:
        # 明确约束 LLM 输出字段，避免自由发挥导致不可解析。
        system_prompt = (
            "你是拍品结构化抽取器。"
            "请从输入文本中抽取字段并严格输出 JSON，不要输出 markdown。"
            '输出格式: {"coin_type":null|"...","variety":null|"...","mint_year":null|"...",'
            '"grading_company":null|"...","grade_score":null|"...","denomination":null|"...",'
            '"special_tags":[],"reason":"..."}。'
            "若无法确定字段，必须返回 null。"
            "coin_type 只能是: 纸币,古钱,机制币,金银锭,章牌杂项。"
            "grading_company 优先标准化为: PCGS,NGC,GBCA,ACA,HUAXIA,YUANDI。"
        )
        payload = {
            "lot_id": lot_id,
            "title": title,
            "description": description,
            "labels": labels,
            "category_hint": category_hint,
        }
        user_prompt = f"请抽取结构化字段: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    @staticmethod
    def _build_llm_fusion_messages(
        lot_id: str,
        title: str,
        description: str,
        labels: list[str],
        category_hint: str,
        llm_payload: dict[str, object],
        rule_payload: dict[str, object],
        conflict_fields: list[str],
    ) -> list[dict[str, str]]:
        system_prompt = (
            "你是拍品结构化融合器。"
            "你会同时看到“LLM结果”和“规则结果”。"
            "请基于原文证据融合两者，不要机械二选一。"
            "输出必须是严格 JSON，不要输出 markdown。"
            '输出格式: {"coin_type":null|"...","variety":null|"...","mint_year":null|"...",'
            '"grading_company":null|"...","grade_score":null|"...","denomination":null|"...",'
            '"special_tags":[],"reason":"..."}。'
            "若字段都不可靠，返回 null。"
            "coin_type 只能是: 纸币,古钱,机制币,金银锭,章牌杂项。"
            "grading_company 标准化为: PCGS,NGC,GBCA,ACA,HUAXIA,YUANDI。"
        )
        payload = {
            "lot_id": lot_id,
            "title": title,
            "description": description,
            "labels": labels,
            "category_hint": category_hint,
            "llm_result": llm_payload,
            "rule_result": rule_payload,
            "conflict_fields": conflict_fields,
        }
        user_prompt = f"请融合结构化字段: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    def _extract_candidate_from_messages(
        self,
        messages: list[dict[str, str]],
        title: str,
        description: str,
        labels: list[str],
        source_tag: str,
        source: str,
    ) -> _Candidate | None:
        if self._settings is None:
            return None
        if time.monotonic() < self._llm_backoff_until:
            return None

        model_chain = [self._settings.default_model]
        if self._settings.fallback_model and self._settings.fallback_model not in model_chain:
            model_chain.append(self._settings.fallback_model)

        network_failures = 0
        attempted = 0
        for model_name in model_chain:
            provider = self._settings.resolve_provider(model_name)
            if provider is None:
                continue
            attempted += 1
            try:
                raw_text = self.chat_completion_fn(
                    provider,
                    model_name,
                    messages,
                    self._settings.temperature,
                    self._settings.max_tokens,
                    self._settings.timeout_seconds,
                )
                parsed = self._parse_model_response(raw_text)
                if parsed is None:
                    continue
                normalized = self._normalize_model_payload(
                    payload=parsed,
                    title=title,
                    description=description,
                    labels=labels,
                    source_tag=source_tag,
                )
                candidate = self._candidate_from_normalized_payload(
                    normalized=normalized,
                    source=source,
                )
                if candidate is None:
                    continue
                self._llm_network_failures = 0
                self._llm_backoff_until = 0.0
                return candidate
            except (HTTPError, URLError, TimeoutError):
                network_failures += 1
                continue
            except (ValueError, KeyError):
                continue

        if attempted > 0 and network_failures == attempted:
            self._llm_network_failures += 1
            if self._llm_network_failures >= 3:
                # 连续网络失败时退避 60 秒，之后自动恢复尝试。
                self._llm_backoff_until = time.monotonic() + 60.0
                self._llm_network_failures = 0
        return None

    def _extract_candidate_by_llm(
        self,
        lot_id: str,
        title: str,
        description: str,
        labels: list[str],
        category_hint: str,
    ) -> _Candidate | None:
        messages = self._build_llm_messages(
            lot_id=lot_id,
            title=title,
            description=description,
            labels=labels,
            category_hint=category_hint,
        )
        return self._extract_candidate_from_messages(
            messages=messages,
            title=title,
            description=description,
            labels=labels,
            source_tag="llm",
            source=self.LLM_EXTRACT_SOURCE,
        )

    def _extract_candidate_by_llm_fusion(
        self,
        lot_id: str,
        title: str,
        description: str,
        labels: list[str],
        category_hint: str,
        llm_candidate: _Candidate,
        rule_candidate: _Candidate,
        conflict_fields: list[str],
    ) -> _Candidate | None:
        messages = self._build_llm_fusion_messages(
            lot_id=lot_id,
            title=title,
            description=description,
            labels=labels,
            category_hint=category_hint,
            llm_payload=self._candidate_to_payload(llm_candidate),
            rule_payload=self._candidate_to_payload(rule_candidate),
            conflict_fields=conflict_fields,
        )
        return self._extract_candidate_from_messages(
            messages=messages,
            title=title,
            description=description,
            labels=labels,
            source_tag="llm_fusion",
            source=self.LLM_FUSION_SOURCE,
        )

    @staticmethod
    def _parse_model_response(text: str) -> dict[str, object] | None:
        cleaned = text.strip()
        if not cleaned:
            return None
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

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
    def _merge_candidates(cls, preferred: _Candidate, fallback: _Candidate, merged_source: str) -> _Candidate:
        def pick(primary: str | None, backup: str | None) -> str | None:
            return primary if primary else backup

        merged_tags: list[str] = []
        for tag in preferred.special_tags + fallback.special_tags:
            if tag and tag not in merged_tags:
                merged_tags.append(tag)
        merged_hits: list[str] = []
        for hit in preferred.rule_hits + fallback.rule_hits:
            if hit and hit not in merged_hits:
                merged_hits.append(hit)

        return _Candidate(
            coin_type=pick(preferred.coin_type, fallback.coin_type),
            variety=pick(preferred.variety, fallback.variety),
            mint_year=pick(preferred.mint_year, fallback.mint_year),
            grading_company=pick(preferred.grading_company, fallback.grading_company),
            grade_score=pick(preferred.grade_score, fallback.grade_score),
            denomination=pick(preferred.denomination, fallback.denomination),
            special_tags=merged_tags,
            rule_hits=merged_hits,
            extract_source=merged_source,
        )

    @staticmethod
    def _normalize_value_for_conflict(value: str | None) -> str | None:
        if value is None:
            return None
        return clean_text(value).upper()

    @classmethod
    def _detect_candidate_conflicts(
        cls,
        llm_candidate: _Candidate,
        rule_candidate: _Candidate,
    ) -> list[str]:
        fields = [
            "coin_type",
            "variety",
            "mint_year",
            "grading_company",
            "grade_score",
            "denomination",
        ]
        conflicts: list[str] = []
        for field in fields:
            llm_value = cls._normalize_value_for_conflict(getattr(llm_candidate, field))
            rule_value = cls._normalize_value_for_conflict(getattr(rule_candidate, field))
            if llm_value and rule_value and llm_value != rule_value:
                conflicts.append(field)
        return conflicts

    @staticmethod
    def _append_rule_hits(candidate: _Candidate, extra_hits: list[str]) -> _Candidate:
        merged_hits: list[str] = list(candidate.rule_hits)
        for hit in extra_hits:
            cleaned = clean_text(hit)
            if cleaned and cleaned not in merged_hits:
                merged_hits.append(cleaned)
        return _Candidate(
            coin_type=candidate.coin_type,
            variety=candidate.variety,
            mint_year=candidate.mint_year,
            grading_company=candidate.grading_company,
            grade_score=candidate.grade_score,
            denomination=candidate.denomination,
            special_tags=candidate.special_tags,
            rule_hits=merged_hits,
            extract_source=candidate.extract_source,
        )

    @classmethod
    def _normalize_model_payload(
        cls,
        payload: dict[str, object],
        title: str,
        description: str,
        labels: list[str],
        source_tag: str,
    ) -> dict[str, object] | None:
        full_text = clean_text(" ".join([title, description, " ".join(labels)]))

        coin_type = cls._normalize_coin_type(payload.get("coin_type"), full_text)
        variety = cls._clean_optional_text(payload.get("variety"))
        mint_year = cls._normalize_mint_year(payload.get("mint_year"), full_text)
        grading_company = cls._normalize_grading_company(payload.get("grading_company"), full_text)
        grade_score = cls._normalize_grade_score(payload.get("grade_score"), full_text)
        denomination = cls._normalize_denomination(payload.get("denomination"), full_text)
        special_tags = cls._normalize_special_tags(payload.get("special_tags"))

        if all(value is None for value in [coin_type, variety, mint_year, grading_company, grade_score, denomination]):
            return None

        rule_hits: list[str] = [source_tag]
        if coin_type:
            rule_hits.append(f"coin_type:{coin_type}")
        if variety:
            rule_hits.append(f"variety:{variety}")
        if mint_year:
            rule_hits.append(f"year:{mint_year}")
        if grading_company:
            rule_hits.append(f"grading_company:{grading_company}")
        if grade_score:
            rule_hits.append(f"grade_score:{grade_score}")
        if denomination:
            rule_hits.append(f"denomination:{denomination}")
        if special_tags:
            rule_hits.append("special_tags")
        return {
            "coin_type": coin_type,
            "variety": variety,
            "mint_year": mint_year,
            "grading_company": grading_company,
            "grade_score": grade_score,
            "denomination": denomination,
            "special_tags": special_tags,
            "rule_hits": rule_hits,
        }

    @classmethod
    def _candidate_from_normalized_payload(
        cls,
        normalized: dict[str, object] | None,
        source: str,
    ) -> _Candidate | None:
        if normalized is None:
            return None
        rule_hits = normalized.get("rule_hits")
        special_tags = normalized.get("special_tags")
        return _Candidate(
            coin_type=normalized.get("coin_type") if isinstance(normalized.get("coin_type"), str) else None,
            variety=normalized.get("variety") if isinstance(normalized.get("variety"), str) else None,
            mint_year=normalized.get("mint_year") if isinstance(normalized.get("mint_year"), str) else None,
            grading_company=normalized.get("grading_company")
            if isinstance(normalized.get("grading_company"), str)
            else None,
            grade_score=normalized.get("grade_score") if isinstance(normalized.get("grade_score"), str) else None,
            denomination=normalized.get("denomination") if isinstance(normalized.get("denomination"), str) else None,
            special_tags=[str(x) for x in special_tags] if isinstance(special_tags, list) else [],
            rule_hits=[str(x) for x in rule_hits] if isinstance(rule_hits, list) else [],
            extract_source=source,
        )

    @classmethod
    def _normalize_coin_type(cls, value: object, text_fallback: str) -> str | None:
        cleaned = cls._clean_optional_text(value)
        if cleaned is not None:
            alias_map = {
                "纸币": "纸币",
                "古钱": "古钱",
                "机制币": "机制币",
                "金银锭": "金银锭",
                "章牌杂项": "章牌杂项",
                "古钱币": "古钱",
                "机制钱币": "机制币",
                "机制银币": "机制币",
            }
            if cleaned in alias_map:
                return alias_map[cleaned]

        parsed, _ = cls._extract_coin_type(text_fallback)
        return parsed

    @classmethod
    def _normalize_grading_company(cls, value: object, text_fallback: str) -> str | None:
        cleaned = cls._clean_optional_text(value)
        if cleaned:
            parsed, _ = cls._extract_grading_company(cleaned)
            if parsed:
                return parsed
            upper = cleaned.upper()
            if upper in {"PCGS", "NGC", "GBCA", "ACA", "HUAXIA", "YUANDI"}:
                return upper
        parsed, _ = cls._extract_grading_company(text_fallback)
        return parsed

    @classmethod
    def _normalize_grade_score(cls, value: object, text_fallback: str) -> str | None:
        cleaned = cls._clean_optional_text(value)
        if cleaned:
            parsed, _ = cls._extract_grade_score(cleaned)
            if parsed:
                return parsed
            # 兼容“美85/极美90”等中文描述分制，避免被过度清洗成空值。
            if re.search(r"(上美|美|极美|未流通|近未流通)\s*[-]?\s*\d{1,3}", cleaned):
                return cleaned[:20]
        parsed, _ = cls._extract_grade_score(text_fallback)
        return parsed

    @classmethod
    def _normalize_denomination(cls, value: object, text_fallback: str) -> str | None:
        cleaned = cls._clean_optional_text(value)
        if cleaned:
            parsed, _ = cls._extract_denomination(cleaned)
            if parsed:
                return parsed
            # 仅保留带明确面值单位的文本，避免“宝武”等伪面值入库。
            if re.search(r"(圆|元|角|分|厘|文|两)", cleaned):
                return cleaned[:20]
            parsed_fallback, _ = cls._extract_denomination(text_fallback)
            return parsed_fallback
        parsed, _ = cls._extract_denomination(text_fallback)
        return parsed

    @classmethod
    def _normalize_mint_year(cls, value: object, text_fallback: str) -> str | None:
        cleaned = cls._clean_optional_text(value)
        if cleaned:
            parsed, _ = cls._extract_mint_year(cleaned)
            if parsed:
                return parsed
            return cleaned[:20]
        parsed, _ = cls._extract_mint_year(text_fallback)
        return parsed

    @classmethod
    def _normalize_special_tags(cls, value: object) -> list[str]:
        items: list[str] = []
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, str):
            raw_items = re.split(r"[，,、|/\s]+", value)
        else:
            raw_items = []
        for item in raw_items:
            cleaned = clean_text(str(item))
            if "省造" in cleaned:
                cleaned = cls._clean_region_tag(cleaned)
            if cleaned and cleaned not in items:
                items.append(cleaned[:32])
            if len(items) >= 10:
                break
        return items

    @staticmethod
    def _clean_optional_text(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        cleaned = clean_text(value)
        if not cleaned:
            return None
        lowered = cleaned.lower()
        if lowered in {"none", "null", "n/a", "unknown", "无法判断"}:
            return None
        return cleaned

    def _extract_candidate(
        self,
        text: str,
        labels: list[str],
        category_hint: str,
        source: str,
    ) -> _Candidate:
        # 从文本中抽取结构化字段，并记录命中的规则证据。
        merged = clean_text(" ".join(part for part in [text, " ".join(labels), category_hint] if part))
        rule_hits: list[str] = []

        coin_type, coin_rule = self._extract_coin_type(merged)
        if coin_rule:
            rule_hits.append(coin_rule)
        variety, variety_rule = self._extract_variety(merged)
        if variety_rule:
            rule_hits.append(variety_rule)
        mint_year, year_rule = self._extract_mint_year(merged)
        if year_rule:
            rule_hits.append(year_rule)
        grading_company, company_rule = self._extract_grading_company(merged)
        if company_rule:
            rule_hits.append(company_rule)
        grade_score, score_rule = self._extract_grade_score(merged)
        if score_rule:
            rule_hits.append(score_rule)
        denomination, denomination_rule = self._extract_denomination(merged)
        if denomination_rule:
            rule_hits.append(denomination_rule)

        special_tags = self._extract_special_tags(merged, labels)
        if special_tags:
            rule_hits.append("special_tags")

        return _Candidate(
            coin_type=coin_type,
            variety=variety,
            mint_year=mint_year,
            grading_company=grading_company,
            grade_score=grade_score,
            denomination=denomination,
            special_tags=special_tags,
            rule_hits=rule_hits,
            extract_source=source,
        )

    def _score_candidate(self, candidate: _Candidate, prefer_title: bool, fallback_used: bool) -> Decimal:
        # 置信度评分：核心字段命中越多分越高，并对回退路径施加轻微惩罚。
        score = Decimal("0.18")
        if candidate.coin_type:
            score += Decimal("0.22")
        if candidate.variety:
            score += Decimal("0.12")
        if candidate.mint_year:
            score += Decimal("0.12")
        if candidate.grading_company:
            score += Decimal("0.16")
        if candidate.grade_score:
            score += Decimal("0.16")
        if candidate.denomination:
            score += Decimal("0.12")
        score += Decimal(str(min(len(candidate.special_tags), 5))) * Decimal("0.02")
        if prefer_title and candidate.core_field_count() >= 2:
            score += Decimal("0.04")
        if fallback_used:
            score -= Decimal("0.03")

        score = max(Decimal("0.01"), min(Decimal("0.99"), score))
        return score.quantize(Decimal("0.01"))

    def _build_review_reason(self, confidence: Decimal, candidate: _Candidate) -> str | None:
        # 低置信度或关键字段缺失时生成复核原因。
        reasons: list[str] = []
        if confidence < self.LOW_CONFIDENCE_THRESHOLD:
            reasons.append(f"置信度偏低({confidence})")
        if candidate.coin_type is None:
            reasons.append("缺少币种")
        if candidate.grade_score and candidate.grading_company is None:
            reasons.append("有分数但缺少评级公司")
        if candidate.core_field_count() <= 1:
            reasons.append("核心字段过少")
        if not reasons:
            return None
        return "；".join(reasons)

    def _schema_fallback_payload(self, lot_id: str, reason: str) -> dict[str, object]:
        # schema 失败兜底输出：固定低置信度并强制进入人工复核队列。
        return {
            "lot_id": lot_id,
            "coin_type": None,
            "variety": None,
            "mint_year": None,
            "grading_company": None,
            "grade_score": None,
            "denomination": None,
            "special_tags": [],
            "rule_hits": ["schema_fallback"],
            "confidence_score": 0.10,
            "extract_source": "schema_fallback",
            "schema_version": self.VERSION,
            "fallback_used": True,
            "needs_manual_review": True,
            "review_reason": f"schema 校验失败: {reason}",
        }

    @staticmethod
    def _parse_labels(labels_json: str | None) -> list[str]:
        # 标签字段兼容 JSON 数组与普通分隔字符串。
        if not labels_json:
            return []
        raw = labels_json.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [clean_text(str(item)) for item in parsed if clean_text(str(item))]
        except json.JSONDecodeError:
            pass
        return [clean_text(item) for item in re.split(r"[，,、|/\s]+", raw) if clean_text(item)]

    @staticmethod
    def _extract_coin_type(text: str) -> tuple[str | None, str | None]:
        # 币种识别按高辨识度词优先。
        rules: list[tuple[str, list[str]]] = [
            ("纸币", ["纸币", "人民币", "银票", "宝钞", "纸钞"]),
            ("金银锭", ["银锭", "金锭", "银条", "金条"]),
            ("章牌杂项", ["纪念章", "章牌", "奖章", "徽章"]),
            # 机制币特征词优先于“元宝/通宝”泛词，避免光绪元宝等被误判为古钱。
            (
                "机制币",
                [
                    "机制币",
                    "银币",
                    "铜元",
                    "袁大头",
                    "孙像",
                    "龙洋",
                    "船洋",
                    "光绪元宝",
                    "宣统元宝",
                    "大清银币",
                    "熊猫币",
                    "熊猫银币",
                    "熊猫金币",
                    "长城",
                    "和字",
                    "纪念币",
                    "龙凤银币",
                ],
            ),
            ("古钱", ["古钱", "通宝", "元宝", "重宝", "花钱", "刀币", "布币"]),
        ]
        for coin_type, keywords in rules:
            for keyword in keywords:
                if keyword in text:
                    return coin_type, f"coin_type:{keyword}"
        return None, None

    @staticmethod
    def _extract_variety(text: str) -> tuple[str | None, str | None]:
        # 版别优先提取显式“反版/错版/X版”模式，其次匹配常见系列词。
        explicit_patterns = [
            r"([A-Za-z0-9一-龥]{0,20}(?:反版|错版|军阀版|精发版|中发版|粗发版|开云版|圈版|甘肃版|天津版|江西版|湖南版|湖北版|福建版|特大字版|大字版|小字版|隶书版|试铸版|开口贝版))",
            r"((?:长尾龙|短尾龙|珍珠龙|凸眼龙|小鼻龙|九尾龙|大头龙|飞龙|坐龙|团龙|七尾龙|八尾|阴阳币|龙凤|双旗|断笔咸|空心叶|三角圆|卷三旗四|DDO复打|小梅花|马尾珠|七分脸|凹肩章|少火焰|异书|逆背|背逆))",
            r"((?:O版|浅O|精发|尖足布[一-龥]{0,4}|尖足1|尖足|大字|星月))",
            r"((?:多种版别|版别))",
            r"(背(?!面|后)[一-龥A-Za-z0-9]{1,12})",
            r"((?:方足布|圆足布|桥足布|类方足布)[-－—]?[一-龥]{0,4})",
            r"(契刀五百)",
        ]
        noise_values = {"背面", "背后", "龙须"}
        for pattern in explicit_patterns:
            explicit = re.search(pattern, text)
            if explicit:
                value = clean_text(explicit.group(1))
                if not value:
                    continue
                value = value.rstrip("，。；,./")
                if value in noise_values:
                    continue
                return value, f"variety:{value}"

        # 常见组合优先：避免“孙像二十一年三鸟壹圆”只命中“孙像”导致信息丢失。
        if "孙像" in text and "三鸟" in text:
            return "孙像三鸟", "variety:孙像三鸟"

        candidates = [
            "袁大头",
            "孙像",
            "三鸟",
            "龙洋",
            "船洋",
            "帆船",
            "明刀",
            "方足布",
            "圆足布",
            "桥足布",
            "大清银币",
            "光绪元宝",
            "宣统元宝",
            "站洋",
            "坐洋",
        ]
        for keyword in candidates:
            if keyword in text:
                return keyword, f"variety:{keyword}"
        return None, None

    @staticmethod
    def _extract_mint_year(text: str) -> tuple[str | None, str | None]:
        # 年份兼容公历年和中文纪年。
        year_match = re.search(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)", text)
        if year_match:
            year = year_match.group(1)
            return year, f"year:{year}"

        zh_match = re.search(r"((?:民国|光绪|宣统)?[一二三四五六七八九十百零〇两廿卅卌]{1,6}年)", text)
        if zh_match:
            value = clean_text(zh_match.group(1))
            return value, f"year:{value}"
        return None, None

    @staticmethod
    def _normalize_for_keyword_match(text: str) -> str:
        # 关键词匹配归一化：去控制/私有区字符与空白，避免“公博评级”被拆断后漏识别。
        normalized = clean_text(text).upper()
        return "".join(
            ch
            for ch in normalized
            if unicodedata.category(ch) not in {"Cc", "Cf", "Co", "Cs", "Cn"} and not ch.isspace()
        )

    @staticmethod
    def _extract_grading_company(text: str) -> tuple[str | None, str | None]:
        # 评级公司识别，统一返回标准名。
        mapping = {
            "PCGS": "PCGS",
            "NGC": "NGC",
            "GBCA": "GBCA",
            "公博评级": "GBCA",
            "公博": "GBCA",
            "北京公博": "GBCA",
            "ACA": "ACA",
            "华夏评级": "HUAXIA",
            "华夏": "HUAXIA",
            "园地评级": "YUANDI",
            "园地": "YUANDI",
        }
        text_upper = TitleDescriptionStructuredAgent._normalize_for_keyword_match(text)
        for key, value in mapping.items():
            if TitleDescriptionStructuredAgent._normalize_for_keyword_match(key) in text_upper:
                return value, f"grading_company:{value}"
        return None, None

    @staticmethod
    def _extract_grade_score(text: str) -> tuple[str | None, str | None]:
        # 评级分识别，支持 MS/AU/XF/VF/PF/SP 前缀。
        # 注意：保留原始分值（如 VF92），不做 70 分上限截断。
        match = re.search(
            r"(?<![A-Z0-9])(MS|AU|XF|VF|F|G|PF|SP|PR|UNC|GENUINE)\s*(?:DETAILS?)?\s*[-（(]?\s*(\d{1,3})(\+?)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            prefix = match.group(1).upper()
            score_text = match.group(2)
            plus = match.group(3) or ""
            score_value = int(score_text)
            if score_value < 1:
                return None, None
            result = f"{prefix}{score_value}{plus}"
            return result, f"grade_score:{result}"

        zh_match = re.search(r"(上美|极美|美|未流通|近未流通)\s*[-（(]?\s*(\d{1,3})\s*[）)]?", text)
        if zh_match:
            zh_score = int(zh_match.group(2))
            if zh_score < 1:
                return None, None
            result = f"{zh_match.group(1)}{zh_score}"
            return result, f"grade_score:{result}"

        company_score_match = re.search(
            r"(PCGS|NGC|GBCA|ACA|HUAXIA|YUANDI|华夏评级|公博评级|园地评级)",
            text,
            flags=re.IGNORECASE,
        )
        if company_score_match:
            trailing = text[company_score_match.end() : company_score_match.end() + 24]
            numbers = [int(x) for x in re.findall(r"\d{1,3}", trailing) if int(x) <= 100]
            if numbers:
                score_value = numbers[-1]
                result = str(score_value)
                return result, f"grade_score:{result}"
        return None, None

    @staticmethod
    def _clean_region_tag(tag: str) -> str:
        cleaned = clean_text(tag)
        if not cleaned:
            return ""
        # 清理年份与干支前缀，再提取完整“xx省造”。
        cleaned = re.sub(r"^\d{2,4}年", "", cleaned)
        cleaned = re.sub(r"^[甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥]{1,2}年?", "", cleaned)
        cleaned = cleaned.lstrip("年")
        tail = re.search(r"([一-龥]{2,6}省造)$", cleaned)
        if tail:
            region = tail.group(1)
            if "年" in region:
                region = region.split("年")[-1]
            region = re.sub(r"^(?:清|中华民国|民国)", "", region)
            region = re.sub(r"^[甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥]{1,2}", "", region)
            short_region = re.search(r"([一-龥]{2,3}省造)$", region)
            if short_region:
                return short_region.group(1)
            return region
        return cleaned

    @staticmethod
    def _extract_denomination(text: str) -> tuple[str | None, str | None]:
        # 面值提取优先固定词表，其次匹配阿拉伯数字+元/角/分。
        fixed_patterns = [
            "中圆",
            "中圓",
            "当百",
            "当五十",
            "当十",
            "当二十",
        ]
        for keyword in fixed_patterns:
            if keyword in text:
                return keyword, f"denomination:{keyword}"

        # 古钱常见单位：釿。
        jin_match = re.search(r"([一二三四五六七八九壹贰叁肆伍陆柒捌玖两]{1,2}釿)", text)
        if jin_match:
            value = clean_text(jin_match.group(1))
            return value, f"denomination:{value}"

        if "契刀五百" in text:
            return "五百", "denomination:五百"

        # 古钱场景常见“重宝...五十”省略“文/当”写法。
        heavy_treasure_match = re.search(
            r"(?:重宝|元宝|通宝)[^，。；,\s]{0,8}?([一二三四五六七八九壹贰叁肆伍陆柒捌玖](?:十|百))",
            text,
        )
        if heavy_treasure_match:
            value = clean_text(heavy_treasure_match.group(1))
            return value, f"denomination:{value}"

        # 清末银币等常见复合面值：七钱二分、七分三厘、同一厘等。
        zh_num = r"[一二三四五六七八九十百千零〇两壹贰叁肆伍陆柒捌玖拾佰仟]"
        compound_patterns = [
            rf"({zh_num}{{1,4}}钱{zh_num}{{1,4}}分(?:{zh_num}{{1,4}}厘)?)",
            rf"({zh_num}{{1,4}}分{zh_num}{{1,4}}厘)",
            rf"(同?{zh_num}{{1,4}}厘)",
            rf"({zh_num}{{1,4}}(?:圆|元|角|分|文|毫|两))",
            rf"({zh_num}{{1,4}}文)",
            r"(\d{1,4}\s*(?:圆|元|角|分|文|厘|毫))",
        ]
        for pattern in compound_patterns:
            for match in re.finditer(pattern, text):
                value = clean_text(match.group(1))
                next_char = text[match.end(1) : match.end(1) + 1]
                # 排除“七分脸”等非面值表达。
                if value.endswith("分") and next_char in {"脸", "面"}:
                    continue
                # 排除“壹元宝/一元宝”等币名片段被误识别为面值。
                if value.endswith(("元", "圆")) and next_char == "宝":
                    continue
                return value, f"denomination:{value}"

        digit_match = re.search(r"(\d+\s*(?:元|角|分|文|厘|毫))", text)
        if digit_match:
            value = clean_text(digit_match.group(1))
            return value, f"denomination:{value}"
        return None, None

    @staticmethod
    def _extract_special_tags(text: str, labels: list[str]) -> list[str]:
        # 特殊标签用于后续人工复核和清洗建模，保留去重后的顺序。
        keywords = [
            "三鸟",
            "七三反版",
            "反版",
            "原味包浆",
            "老包浆",
            "错版",
            "样币",
            "冠军分",
            "低评高分",
            "原光",
            "五彩",
            "清洗",
            "修补",
            "划痕",
            "评级币",
            "裸币",
            "保真",
            "带戳记",
        ]
        ordered: list[str] = []
        for keyword in keywords:
            if keyword in text and keyword not in ordered:
                ordered.append(keyword)
        # 产地信息保留为标签，避免“广东省造”这类原始关键信息丢失。
        for region in re.findall(r"([一-龥]{2,6}省造)", text):
            cleaned_region = TitleDescriptionStructuredAgent._clean_region_tag(region)
            if cleaned_region and cleaned_region not in ordered:
                ordered.append(cleaned_region)
        for label in labels:
            cleaned = clean_text(label)
            if "省造" in cleaned:
                cleaned = TitleDescriptionStructuredAgent._clean_region_tag(cleaned)
            if cleaned and cleaned not in ordered:
                ordered.append(cleaned)
        return ordered

    def _validate_payload(self, payload: dict[str, object]) -> str | None:
        # 轻量 JSON Schema 校验：覆盖 required/type/enum/range 关键约束。
        schema = self.OUTPUT_JSON_SCHEMA
        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [key for key in required if key not in payload]
            if missing:
                return f"缺少字段: {','.join(str(x) for x in missing)}"

        if not isinstance(payload.get("lot_id"), str) or not str(payload.get("lot_id")):
            return "lot_id 非法"

        nullable_text_keys = [
            "coin_type",
            "variety",
            "mint_year",
            "grading_company",
            "grade_score",
            "denomination",
            "review_reason",
        ]
        for key in nullable_text_keys:
            value = payload.get(key)
            if value is not None and not isinstance(value, str):
                return f"{key} 类型非法"

        for key in ["special_tags", "rule_hits"]:
            value = payload.get(key)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                return f"{key} 类型非法"

        confidence = payload.get("confidence_score")
        if not isinstance(confidence, (int, float)):
            return "confidence_score 类型非法"
        if float(confidence) < 0.0 or float(confidence) > 1.0:
            return "confidence_score 越界"

        source = payload.get("extract_source")
        if source not in {
            "title_rules",
            "fallback_rules",
            "llm_structured",
            "llm_structured_with_rule_fill",
            "llm_fusion",
            "llm_fusion_with_rule_fill",
            "react_structured",
            "react_structured_with_rule_fill",
            "schema_fallback",
        }:
            return "extract_source 非法"

        for key in ["fallback_used", "needs_manual_review"]:
            if not isinstance(payload.get(key), bool):
                return f"{key} 类型非法"

        schema_version = payload.get("schema_version")
        if not isinstance(schema_version, str) or not schema_version:
            return "schema_version 非法"

        # additionalProperties=false：不允许额外字段。
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            extra = [key for key in payload.keys() if key not in properties]
            if extra:
                return f"包含未声明字段: {','.join(extra)}"

        return None
