from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.orchestration.model_settings import ProviderConfig
from src.structuring.title_description_structured_agent import TitleDescriptionStructuredAgent


class TitleDescriptionStructuredAgentTestCase(unittest.TestCase):
    def _write_temp_yaml(self, content: str) -> Path:
        temp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        temp.write(content)
        temp.flush()
        temp.close()
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        return Path(temp.name)

    def setUp(self) -> None:
        # 每个用例独立实例，避免状态串扰。
        self.agent = TitleDescriptionStructuredAgent()

    def test_clean_extracts_core_fields_from_title(self) -> None:
        # 标题中信息完整时，应抽出核心字段且不进入复核。
        result = self.agent.clean(
            lot_id="l1",
            title="PCGS MS64 袁大头 三年 壹圆 原味包浆",
            description="老包浆",
            labels_json='["评级币"]',
            category_hint="机制币",
        )
        self.assertEqual("l1", result.lot_id)
        self.assertEqual("机制币", result.coin_type)
        self.assertEqual("袁大头", result.variety)
        self.assertEqual("PCGS", result.grading_company)
        self.assertEqual("MS64", result.grade_score)
        self.assertEqual("壹圆", result.denomination)
        self.assertIn("原味包浆", result.special_tags)
        self.assertGreaterEqual(result.confidence_score, Decimal("0.80"))
        self.assertFalse(result.needs_manual_review)

    def test_clean_uses_fallback_rules_when_title_is_sparse(self) -> None:
        # 标题信息不足但描述可抽取时，应触发回退规则并提升结果完整度。
        result = self.agent.clean(
            lot_id="l2",
            title="精品拍品",
            description="NGC AU55 孙像二十一年壹圆",
            labels_json=None,
            category_hint=None,
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual("机制币", result.coin_type)
        self.assertEqual("孙像", result.variety)
        self.assertEqual("NGC", result.grading_company)
        self.assertEqual("AU55", result.grade_score)
        self.assertIsNotNone(result.mint_year)

    def test_clean_keeps_composite_variety_and_region_tag(self) -> None:
        # “孙像+三鸟”“广东省造+七三反版”这类关键信息不应被覆盖或丢失。
        result_a = self.agent.clean(
            lot_id="l2a",
            title="PCGS-MS61 孙像二十一年三鸟壹圆 欧洲纸袋包浆",
            description="",
            labels_json='["机制币","银币","PCGS"]',
            category_hint="机制币",
        )
        self.assertEqual("孙像三鸟", result_a.variety)
        self.assertIn("三鸟", result_a.special_tags)

        result_b = self.agent.clean(
            lot_id="l2b",
            title="PCGS-VF92 广东省造光绪元宝七分三厘 七三反版",
            description="",
            labels_json='["机制币","银币","PCGS"]',
            category_hint="机制币",
        )
        self.assertEqual("七三反版", result_b.variety)
        self.assertIn("广东省造", result_b.special_tags)
        self.assertIn("七三反版", result_b.special_tags)
        self.assertEqual("VF92", result_b.grade_score)

    def test_clean_extracts_compound_denomination(self) -> None:
        # 清末银币常见面值写法应能识别，避免面值字段空缺。
        result_a = self.agent.clean(
            lot_id="l2c",
            title="（PCGS-VF97）三十四年北洋造光绪元宝银币七钱二分 长尾龙",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("七钱二分", result_a.denomination)

        result_b = self.agent.clean(
            lot_id="l2d",
            title="（华夏评级 极美84）顺治通宝同一厘",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertEqual("同一厘", result_b.denomination)

        result_c = self.agent.clean(
            lot_id="l2e",
            title="（华夏评级 58）中国人民银行伍圆 帆船",
            description="",
            labels_json='["纸币"]',
            category_hint="纸币",
        )
        self.assertEqual("伍圆", result_c.denomination)

    def test_clean_extracts_complex_denomination_without_truncation(self) -> None:
        # “五十文/二十文/500文/重宝五十”等不能被截断成“十文”。
        result_a = self.agent.clean(
            lot_id="l2e2",
            title="（PCGS XF40）苏维埃500文",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("500文", result_a.denomination)

        result_b = self.agent.clean(
            lot_id="l2e3",
            title="（PCGS MS63）湖南二十文嘉禾旗上星",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("二十文", result_b.denomination)

        result_c = self.agent.clean(
            lot_id="l2e4",
            title="咸丰重宝宝河五十（公博评级 美85）",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertEqual("五十", result_c.denomination)

    def test_clean_extracts_more_denomination_and_skips_false_hits(self) -> None:
        # 补充“贰佰文/贰毫/一百/一两”，并避免“七分脸”“壹元宝”误提。
        result_a = self.agent.clean(
            lot_id="l2e5",
            title="（华夏评级 VF 35）河南贰佰文",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("贰佰文", result_a.denomination)

        result_b = self.agent.clean(
            lot_id="l2e6",
            title="民国广西省造中华民国三十八年贰毫银币",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("贰毫", result_b.denomination)

        result_c = self.agent.clean(
            lot_id="l2e7",
            title="咸丰通宝宝福一百（公博评级 美90）",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertEqual("一百", result_c.denomination)

        result_d = self.agent.clean(
            lot_id="l2e8",
            title="（PCGS-VF98）饷银一两",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("一两", result_d.denomination)

        result_e = self.agent.clean(
            lot_id="l2e9",
            title="民国三年袁世凯像七分脸壹圆 仿品",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("壹圆", result_e.denomination)

        result_f = self.agent.clean(
            lot_id="l2e10",
            title="（华夏评级 极美86）得壹元宝背上月",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertIsNone(result_f.denomination)

        result_g = self.agent.clean(
            lot_id="l2e11",
            title="桥足布-梁一釿（公博评级 美90）",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertEqual("一釿", result_g.denomination)

        result_h = self.agent.clean(
            lot_id="l2e12",
            title="契刀五百（公博评级 美90）",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertEqual("五百", result_h.denomination)

    def test_clean_parses_details_style_grade(self) -> None:
        # XF(92 - Cleaned)、PR65DCAM 等 details 写法应保留分数。
        result_a = self.agent.clean(
            lot_id="l2f",
            title="（PCGS-XF（92 - Cleaned））1901年四川省造光绪元宝银币七钱二分",
            description="",
            labels_json='["机制币","银币","PCGS"]',
            category_hint="机制币",
        )
        self.assertEqual("XF92", result_a.grade_score)

        result_b = self.agent.clean(
            lot_id="l2g",
            title="（PCGS PR65DCAM）2013年熊猫银币50元 5盎司",
            description="",
            labels_json='["机制币","现代金银币","PCGS"]',
            category_hint="机制币",
        )
        self.assertEqual("PR65", result_b.grade_score)

    def test_clean_parses_grade_without_word_boundary_and_parentheses(self) -> None:
        # “评级AU50”“极美（05）”这类写法也应识别分数。
        result_a = self.agent.clean(
            lot_id="l2g3",
            title="九年大头 中发版 原华夏评级AU50，评级编号5570016406，已砸盒",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("AU50", result_a.grade_score)
        self.assertEqual("HUAXIA", result_a.grading_company)

        result_b = self.agent.clean(
            lot_id="l2g4",
            title="（华夏评级 极美（05））大定通宝小平大样",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertEqual("极美5", result_b.grade_score)

        result_c = self.agent.clean(
            lot_id="l2g5",
            title="（华夏评级 80）金钱义记小离版",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertEqual("80", result_c.grade_score)

        result_d = self.agent.clean(
            lot_id="l2g6",
            title="（华夏评级（06） 55）中国人民银行壹佰圆 红轮船",
            description="",
            labels_json='["纸币"]',
            category_hint="纸币",
        )
        self.assertEqual("55", result_d.grade_score)

    def test_clean_parses_zh_grade_score(self) -> None:
        # 中文分制不能丢（之前曾出现分支不可达导致提取失败）。
        result = self.agent.clean(
            lot_id="l2g2",
            title="（华夏评级 极美84）咸丰重宝当十",
            description="",
            labels_json='["古钱","华夏评级"]',
            category_hint="古钱",
        )
        self.assertEqual("极美84", result.grade_score)
        self.assertEqual("HUAXIA", result.grading_company)

    def test_clean_coin_type_prefers_modern_for_guangxu_yuanbao(self) -> None:
        # 光绪/宣统元宝银币属于机制币，不应被“元宝”泛词误判为古钱。
        result = self.agent.clean(
            lot_id="l2h",
            title="（PCGS-XF45）1908年造币总厂光绪元宝银币七钱二分",
            description="",
            labels_json='["机制币","银币","PCGS"]',
            category_hint="机制币",
        )
        self.assertEqual("机制币", result.coin_type)

        result_hezhi = self.agent.clean(
            lot_id="l2h2",
            title="（NGC PF68ULTRACAMEO）和字壹圆（精制）",
            description="",
            labels_json='["现代金银币","NGC"]',
            category_hint="机制币",
        )
        self.assertEqual("机制币", result_hezhi.coin_type)

    def test_clean_variety_should_not_capture_year_text(self) -> None:
        # 年份应进入 mint_year，不应误写入 variety。
        result = self.agent.clean(
            lot_id="l2h3",
            title="大清铜币十文 · 宣统三年（园地评级 XF40）",
            description="",
            labels_json='["机制币","铜板"]',
            category_hint="机制币",
        )
        self.assertEqual("宣统三年", result.mint_year)
        self.assertIsNone(result.variety)

        result_38 = self.agent.clean(
            lot_id="l2h4",
            title="新疆省造币厂铸民国卅八年壹元",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("民国卅八年", result_38.mint_year)

    def test_clean_extracts_variety_keywords(self) -> None:
        # 版别关键信号应尽量入 variety，避免信息白白丢失。
        result_a = self.agent.clean(
            lot_id="l2h5",
            title="PCGS-XF45 北洋34年七钱二分 长尾龙",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("长尾龙", result_a.variety)

        result_b = self.agent.clean(
            lot_id="l2h6",
            title="民国三年袁世凯像七分脸壹圆 仿品",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("七分脸", result_b.variety)

        result_c = self.agent.clean(
            lot_id="l2h7",
            title="九年大头 精发版",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("精发版", result_c.variety)

        result_d = self.agent.clean(
            lot_id="l2h8",
            title="（华夏评级 XF 45）喀什造大清銀幣回曆1327年／逆背",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("逆背", result_d.variety)

        result_e = self.agent.clean(
            lot_id="l2h9",
            title="方足布-安阳（公博评级 美90）",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertTrue(result_e.variety is not None and result_e.variety.startswith("方足布"))

        result_f = self.agent.clean(
            lot_id="l2h10",
            title="（PCGS-AU50）民国三年袁世凯像银币壹圆 O版",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("O版", result_f.variety)

        result_g = self.agent.clean(
            lot_id="l2h11",
            title="（华夏评级 极美84）尖足布晋阳半",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertTrue(result_g.variety is not None and result_g.variety.startswith("尖足布"))

        result_h = self.agent.clean(
            lot_id="l2h12",
            title="崇宁通宝 一组2枚（版别）",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertEqual("版别", result_h.variety)

    def test_clean_special_tags_keeps_clean_province_name(self) -> None:
        # 省造标签不应带“年”前缀噪声。
        result = self.agent.clean(
            lot_id="l2i",
            title="（PCGS XF45）1909年湖北省造宣统元宝银币七钱二分",
            description="",
            labels_json='["机制币","银币","PCGS"]',
            category_hint="机制币",
        )
        self.assertIn("湖北省造", result.special_tags)
        self.assertNotIn("年湖北省造", result.special_tags)

        result_sc = self.agent.clean(
            lot_id="l2i3",
            title="（PCGS XF92）1901年四川省造光绪元宝银币七钱二分",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertIn("四川省造", result_sc.special_tags)
        self.assertNotIn("川省造", result_sc.special_tags)

        result_qy = self.agent.clean(
            lot_id="l2i4",
            title="（PCGS VF30）清乙巳年江南省造库平七钱二分光绪元宝",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertIn("江南省造", result_qy.special_tags)
        self.assertNotIn("清乙巳年江南省造", result_qy.special_tags)

    def test_clean_special_tags_strips_stem_branch_prefix(self) -> None:
        # “甲辰/戊戌/子年”等前缀应清理为标准“xx省造”。
        result = self.agent.clean(
            lot_id="l2i2",
            title="（PCGS XF45）甲辰江南省造光绪元宝七钱二分",
            description="戊戌江南省造同版",
            labels_json='["子年江南省造","机制币"]',
            category_hint="机制币",
        )
        self.assertIn("江南省造", result.special_tags)
        self.assertNotIn("甲辰江南省造", result.special_tags)
        self.assertNotIn("戊戌江南省造", result.special_tags)
        self.assertNotIn("子年江南省造", result.special_tags)

    def test_clean_llm_denomination_noise_should_be_dropped(self) -> None:
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
  max_tokens: 200
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

        def fake_chat(
            provider: ProviderConfig,
            model_name: str,
            messages,
            temperature: float,
            max_tokens: int,
            timeout_seconds: float,
        ) -> str:
            return (
                '{"coin_type":"古钱","variety":"雍正通宝","mint_year":null,'
                '"grading_company":"公博评级","grade_score":"美80","denomination":"宝武","special_tags":[]}'
            )

        llm_agent = TitleDescriptionStructuredAgent(
            enable_llm=True,
            settings_path=settings_path,
            chat_completion_fn=fake_chat,
        )
        result = llm_agent.clean(
            lot_id="l2i",
            title="雍正通宝 宝 武（公博评级 美80）",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
        )
        self.assertIsNone(result.denomination)

    def test_clean_marks_manual_review_for_low_confidence(self) -> None:
        # 关键信息缺失时必须进入人工复核队列。
        result = self.agent.clean(
            lot_id="l3",
            title="测试样本",
            description="品相如图",
            labels_json="",
            category_hint="",
        )
        self.assertTrue(result.needs_manual_review)
        self.assertIsNotNone(result.review_reason)
        self.assertLess(result.confidence_score, self.agent.LOW_CONFIDENCE_THRESHOLD)

    def test_clean_extracts_gbca_company_from_gongbo_text(self) -> None:
        # “公博评级”应识别为评级公司，避免“有分数但缺少评级公司”误报。
        result = self.agent.clean(
            lot_id="l4",
            title="白塔五分（公博评级 XF45）",
            description="后附评级官网图",
            labels_json='["机制币","铜板"]',
            category_hint="机制币",
        )
        self.assertEqual("GBCA", result.grading_company)
        self.assertEqual("XF45", result.grade_score)
        self.assertTrue(result.review_reason is None or "有分数但缺少评级公司" not in result.review_reason)

    def test_clean_extracts_yuandi_company_from_yuandi_text(self) -> None:
        # “园地评级”应识别为评级公司。
        result = self.agent.clean(
            lot_id="l5",
            title="大清铜币十文（园地评级 XF40）",
            description="评级币",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("YUANDI", result.grading_company)
        self.assertEqual("XF40", result.grade_score)
        self.assertTrue(result.review_reason is None or "有分数但缺少评级公司" not in result.review_reason)

    def test_clean_extracts_company_when_text_contains_private_use_chars(self) -> None:
        # 文本中混入私有区字符时，仍应识别“公博评级”。
        result = self.agent.clean(
            lot_id="l6",
            title="白塔五分（公\ue000博\ue000评\ue000级 XF45）",
            description="后附评级官网图",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual("GBCA", result.grading_company)
        self.assertEqual("XF45", result.grade_score)
        self.assertTrue(result.review_reason is None or "有分数但缺少评级公司" not in result.review_reason)

    def test_clean_prefers_llm_when_enabled(self) -> None:
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
  max_tokens: 200
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

        called: list[str] = []

        def fake_chat(
            provider: ProviderConfig,
            model_name: str,
            messages,
            temperature: float,
            max_tokens: int,
            timeout_seconds: float,
        ) -> str:
            called.append(model_name)
            self.assertEqual("siliconflow", provider.name)
            return (
                '{"coin_type":"机制币","variety":"小B宝","mint_year":null,'
                '"grading_company":"公博评级","grade_score":"XF02","denomination":null,'
                '"special_tags":["评级币"],"reason":"llm structured"}'
            )

        llm_agent = TitleDescriptionStructuredAgent(
            enable_llm=True,
            settings_path=settings_path,
            chat_completion_fn=fake_chat,
        )
        result = llm_agent.clean(
            lot_id="l7",
            title="浙江黄铜 小B宝（公博评级 XF02）",
            description="后附评级官网图",
            labels_json='["机制币"]',
            category_hint="机制币",
        )

        self.assertEqual(["moonshotai/Kimi-K2-Instruct"], called)
        self.assertEqual("GBCA", result.grading_company)
        self.assertEqual("XF2", result.grade_score)
        self.assertEqual("llm_structured_with_rule_fill", result.extract_source)
        self.assertGreaterEqual(result.confidence_score, Decimal("0.80"))
        self.assertFalse(result.needs_manual_review)

    def test_clean_uses_llm_fusion_when_llm_conflicts_with_rules(self) -> None:
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
  max_tokens: 200
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

        calls = {"n": 0}

        def fake_chat(
            provider: ProviderConfig,
            model_name: str,
            messages,
            temperature: float,
            max_tokens: int,
            timeout_seconds: float,
        ) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                # 第一轮 LLM 与规则冲突：给出“短尾龙”。
                return (
                    '{"coin_type":"机制币","variety":"短尾龙","mint_year":null,'
                    '"grading_company":"PCGS","grade_score":"XF45","denomination":"七钱二分","special_tags":[]}'
                )
            # 第二轮融合：采纳规则证据“长尾龙”。
            return (
                '{"coin_type":"机制币","variety":"长尾龙","mint_year":null,'
                '"grading_company":"PCGS","grade_score":"XF45","denomination":"七钱二分","special_tags":[]}'
            )

        llm_agent = TitleDescriptionStructuredAgent(
            enable_llm=True,
            settings_path=settings_path,
            chat_completion_fn=fake_chat,
        )
        result = llm_agent.clean(
            lot_id="l7b",
            title="PCGS-XF45 北洋34年七钱二分 长尾龙",
            description="",
            labels_json='["机制币"]',
            category_hint="机制币",
        )
        self.assertEqual(2, calls["n"])
        self.assertEqual("长尾龙", result.variety)
        self.assertEqual("llm_fusion_with_rule_fill", result.extract_source)
        payload = result.to_payload()
        self.assertIn("llm_fusion_conflict:variety", payload.get("rule_hits", []))

    def test_clean_falls_back_to_rules_when_llm_fails(self) -> None:
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
  max_tokens: 200
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

        def fake_chat(
            provider: ProviderConfig,
            model_name: str,
            messages,
            temperature: float,
            max_tokens: int,
            timeout_seconds: float,
        ) -> str:
            raise TimeoutError("network down")

        llm_agent = TitleDescriptionStructuredAgent(
            enable_llm=True,
            settings_path=settings_path,
            chat_completion_fn=fake_chat,
        )
        result = llm_agent.clean(
            lot_id="l8",
            title="PCGS MS64 袁大头 三年 壹圆 原味包浆",
            description="老包浆",
            labels_json='["评级币"]',
            category_hint="机制币",
        )
        self.assertEqual("PCGS", result.grading_company)
        self.assertEqual("MS64", result.grade_score)
        self.assertIn(result.extract_source, {"title_rules", "fallback_rules"})

    def test_clean_uses_react_when_enabled_for_structure_task(self) -> None:
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
  max_tokens: 200
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
        calls = {"n": 0}

        def fake_chat(
            provider: ProviderConfig,
            model_name: str,
            messages,
            temperature: float,
            max_tokens: int,
            timeout_seconds: float,
        ) -> str:
            calls["n"] += 1
            # 第1次给 llm 单轮抽取返回无效结果，促使进入 react；
            # 第2次返回 action；第3次返回 final。
            if calls["n"] == 1:
                return '{"type":"action","action":"rule_extract","args":{}}'
            if calls["n"] == 2:
                return '{"type":"action","action":"find_keyword","args":{"keyword":"方足布"}}'
            return (
                '{"type":"final","result":{"coin_type":"古钱","variety":"方足布北屈","mint_year":null,'
                '"grading_company":null,"grade_score":null,"denomination":null,"special_tags":["古钱"]},'
                '"reason":"react done"}'
            )

        react_agent = TitleDescriptionStructuredAgent(
            enable_llm=True,
            settings_path=settings_path,
            chat_completion_fn=fake_chat,
            enable_react=True,
            react_max_steps=3,
        )
        result = react_agent.clean(
            lot_id="l9",
            title="方足布北屈",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
            use_react=True,
        )
        self.assertGreaterEqual(calls["n"], 3)
        self.assertEqual("方足布北屈", result.variety)
        self.assertEqual("react_structured_with_rule_fill", result.extract_source)

    def test_clean_not_use_react_when_flag_is_false(self) -> None:
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
  max_tokens: 200
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
        calls = {"n": 0}

        def fake_chat(
            provider: ProviderConfig,
            model_name: str,
            messages,
            temperature: float,
            max_tokens: int,
            timeout_seconds: float,
        ) -> str:
            calls["n"] += 1
            return (
                '{"coin_type":"古钱","variety":"方足布中都","mint_year":null,'
                '"grading_company":null,"grade_score":null,"denomination":null,"special_tags":[]}'
            )

        agent = TitleDescriptionStructuredAgent(
            enable_llm=True,
            settings_path=settings_path,
            chat_completion_fn=fake_chat,
            enable_react=True,
            react_max_steps=3,
        )
        result = agent.clean(
            lot_id="l10",
            title="方足布中都",
            description="",
            labels_json='["古钱"]',
            category_hint="古钱",
            use_react=False,
        )
        # 仅调用 llm 单轮，不进入 react 多步。
        self.assertEqual(1, calls["n"])
        self.assertEqual("llm_structured_with_rule_fill", result.extract_source)


if __name__ == "__main__":
    unittest.main()
