from __future__ import annotations

import unittest

from src.classification.lot_classifier_agent import LotClassifierAgent


class LotClassifierAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 每个测试用新的分类智能体实例，避免状态污染。
        self.agent = LotClassifierAgent()

    def test_classify_mechanism_coin_by_labels(self) -> None:
        # labels 命中“机制币”时应归入机制币类目。
        result = self.agent.classify(
            title="PCGS-MS61 孙像二十一年三鸟壹圆",
            description="最后一张图为官网图",
            labels_json='["机制币","银币","PCGS"]',
            session_title="天津站机制币古钱专场",
        )
        self.assertEqual("机制币", result.category_l1)
        self.assertEqual("银币", result.category_l2)
        self.assertTrue(result.rule_hit.startswith("labels:"))

    def test_classify_ancient_coin_by_title(self) -> None:
        # 标题命中“通宝/古钱”关键词时应归入古钱。
        result = self.agent.classify(
            title="北宋 元丰通宝 小平",
            description="品相如图",
            labels_json=None,
            session_title="古钱专场",
        )
        self.assertEqual("古钱", result.category_l1)
        self.assertIsNone(result.category_l2)
        self.assertTrue(result.rule_hit.startswith("title:"))

    def test_classify_default_when_unknown(self) -> None:
        # 无法命中规则时回退未分类。
        result = self.agent.classify(
            title="未知测试样本",
            description=None,
            labels_json="",
            session_title="",
        )
        self.assertEqual("未分类", result.category_l1)
        self.assertEqual("default", result.rule_hit)


if __name__ == "__main__":
    unittest.main()
