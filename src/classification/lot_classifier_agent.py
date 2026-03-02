from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal

from src.scraping.normalizers import clean_text


@dataclass(frozen=True)
class ClassificationResult:
    # 分类智能体输出：分类层级、命中标签、规则来源和置信度。
    category_l1: str
    category_l2: str | None
    tags: list[str]
    rule_hit: str
    confidence_score: Decimal


class LotClassifierAgent:
    # 版本号写入数据库，便于后续回溯规则变更。
    VERSION = "rule-v1"

    def classify(
        self,
        title: str,
        description: str | None,
        labels_json: str | None,
        session_title: str | None,
    ) -> ClassificationResult:
        # 基于标题/描述/标签/专场名进行规则分类。
        labels = self._parse_labels(labels_json)
        label_text = " ".join(labels)
        title_text = clean_text(title)
        desc_text = clean_text(description)
        session_text = clean_text(session_title)

        # labels 的语义优先级最高，命中即给高置信度。
        by_labels = self._classify_by_text(label_text)
        if by_labels is not None:
            return ClassificationResult(
                category_l1=by_labels[0],
                category_l2=by_labels[1],
                tags=labels,
                rule_hit=f"labels:{by_labels[2]}",
                confidence_score=Decimal("0.95"),
            )

        # 标题通常包含最核心信息，次优先级。
        by_title = self._classify_by_text(title_text)
        if by_title is not None:
            return ClassificationResult(
                category_l1=by_title[0],
                category_l2=by_title[1],
                tags=labels,
                rule_hit=f"title:{by_title[2]}",
                confidence_score=Decimal("0.86"),
            )

        # 描述字段有一定噪声，置信度低于标题。
        by_desc = self._classify_by_text(desc_text)
        if by_desc is not None:
            return ClassificationResult(
                category_l1=by_desc[0],
                category_l2=by_desc[1],
                tags=labels,
                rule_hit=f"description:{by_desc[2]}",
                confidence_score=Decimal("0.72"),
            )

        # 专场标题只做兜底，避免误判。
        by_session = self._classify_by_text(session_text)
        if by_session is not None:
            return ClassificationResult(
                category_l1=by_session[0],
                category_l2=by_session[1],
                tags=labels,
                rule_hit=f"session:{by_session[2]}",
                confidence_score=Decimal("0.60"),
            )

        return ClassificationResult(
            category_l1="未分类",
            category_l2=None,
            tags=labels,
            rule_hit="default",
            confidence_score=Decimal("0.20"),
        )

    @staticmethod
    def _parse_labels(labels_json: str | None) -> list[str]:
        # 标签字段兼容 JSON 数组、普通字符串两种来源。
        if not labels_json:
            return []
        text = labels_json.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [clean_text(str(item)) for item in parsed if clean_text(str(item))]
        except json.JSONDecodeError:
            pass
        # 非 JSON 时，按常见分隔符切分。
        return [clean_text(x) for x in re.split(r"[，,、|/\s]+", text) if clean_text(x)]

    @staticmethod
    def _contains_any(text: str, keywords: list[str]) -> str | None:
        # 命中任一关键词时返回命中的关键词文本。
        for keyword in keywords:
            if keyword and keyword in text:
                return keyword
        return None

    def _classify_by_text(self, text: str) -> tuple[str, str | None, str] | None:
        # 分类规则：先判定一级类目，再补充二级类目。
        if not text:
            return None

        paper_hit = self._contains_any(text, ["纸币", "钞", "人民币", "银票", "宝钞"])
        if paper_hit:
            return ("纸币", None, paper_hit)

        ancient_hit = self._contains_any(text, ["古钱", "通宝", "元宝", "重宝", "花钱", "刀币", "布币", "古泉"])
        if ancient_hit:
            return ("古钱", None, ancient_hit)

        bullion_hit = self._contains_any(text, ["银锭", "金锭", "元宝锭", "银条", "金条"])
        if bullion_hit:
            return ("金银锭", None, bullion_hit)

        medal_hit = self._contains_any(text, ["纪念章", "章牌", "奖章", "徽章"])
        if medal_hit:
            return ("章牌杂项", "章牌", medal_hit)

        mechanism_hit = self._contains_any(
            text,
            ["机制币", "银币", "铜元", "袁大头", "孙像", "光绪元宝", "大清银币", "纪念币", "龙洋", "船洋"],
        )
        if mechanism_hit:
            category_l2 = self._guess_mechanism_subtype(text)
            return ("机制币", category_l2, mechanism_hit)

        return None

    def _guess_mechanism_subtype(self, text: str) -> str | None:
        # 机制币二级分类，优先区分银币、铜元、纪念币。
        if self._contains_any(text, ["银币", "袁大头", "龙洋", "船洋", "壹圆"]):
            return "银币"
        if self._contains_any(text, ["铜元", "当十", "当二十"]):
            return "铜元"
        if self._contains_any(text, ["纪念币", "纪念章"]):
            return "纪念币"
        return None
