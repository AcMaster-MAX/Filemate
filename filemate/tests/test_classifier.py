"""分类模块测试。TODO(张金宝)"""
from __future__ import annotations

import pytest

# 分类输出契约（技术决策定稿 §4.1）
EXPECTED_FIELDS = {"category", "confidence", "course_name", "method"}


def _make_classifier(llm_client_stub=None):
    """构建一个可测试的 Classifier。llm_client_stub 可注入假响应。"""
    from filemate.understanding.classifier import Classifier

    if llm_client_stub is None:
        class _Stub:
            def call(self, prompt="", messages=None, **kw):
                return '{"category": "待确认", "confidence": 0.5, "course_name": null}'
            def call_structured(self, prompt="", messages=None, **kw):
                return {"category": "待确认", "confidence": 0.5, "course_name": None}
        llm_client_stub = _Stub()
    return Classifier(llm_client_stub, rules_path=None)


from filemate.core.categories import CATEGORIES


class TestClassifierContract:
    """验证分类器输出符合接口契约。"""

    def test_output_keys(self) -> None:
        clf = _make_classifier()
        result = clf.classify("这是一份课件讲义")
        for key in EXPECTED_FIELDS:
            assert key in result, f"输出缺少字段: {key}"

    def test_category_in_set(self) -> None:
        clf = _make_classifier()
        result = clf.classify("随便什么文本")
        assert result["category"] in set(CATEGORIES), f"category={result['category']} 不合法"

    def test_confidence_range(self) -> None:
        clf = _make_classifier()
        result = clf.classify("任意文本")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_keyword_hit_high_confidence(self) -> None:
        """关键词命中 → 置信度落在规则引擎区间内。

        当前公式（classifier.py `_rule_match`，PR #4 review 第 3 项后）::

            ambiguity   = 1.0 if 只命中一个类别 else 0.85
            confidence  = min(ambiguity * (0.35 + 命中数 * 0.05), 0.55)

        即单类别 1 次命中 0.40、4 次命中封顶 0.55；多类别分散命中再乘 0.85，
        理论下限 0.34。故区间为 [0.34, 0.55]。

        TODO(张金宝): 与胡希确认 —— review 只要求加竞争惩罚（ambiguity），
        但基础值同时从 0.55 降到 0.35、上限从 0.92 降到 0.55，超出 review
        范围。实测确认此改动对准确率无影响（预测类别只取决于 max(scores)，
        置信度不参与判断），但会导致规则命中 (0.40) 低于 LLM 兜底默认值
        (0.5)，与"规则比 LLM 更可信"的设计意图相反，且下游按置信度做阈值
        判断的逻辑（确认层提示、自动归档）会受影响。确认后同步调整本断言。

        注：同次 review 一并删除的模糊降级逻辑已恢复，见 commit 3d5875e
        （删除导致 57 份样本准确率 86.79% → 75.47%，恢复后复原）。
        """
        clf = _make_classifier()
        result = clf.classify("本周作业第三章习题")
        if result.get("method") == "rule":
            assert 0.34 <= result["confidence"] <= 0.55, (
                f"规则命中置信度 {result['confidence']} 超出当前区间 [0.34, 0.55]"
            )


class TestClassifierEdgeCases:
    """边界情况。"""

    def test_empty_text(self) -> None:
        clf = _make_classifier()
        result = clf.classify("")
        assert result["category"] == "待确认" or result["category"] in {
            "课件", "作业", "竞赛通知", "考试通知", "参考资料", "大创通知"
        }

    def test_short_text(self) -> None:
        clf = _make_classifier()
        result = clf.classify("作业")
        assert "category" in result

    def test_mixed_language(self) -> None:
        clf = _make_classifier()
        result = clf.classify("实验 lab3 deadline 2026-04-15")
        assert "category" in result


class TestClassifierKeywordRules:
    """关键词规则库。"""

    def test_rules_loaded(self) -> None:
        """规则库非空。"""
        import json
        from pathlib import Path
        rules_path = Path(__file__).resolve().parent.parent / "understanding" / "rules" / "keywords.json"
        if rules_path.exists():
            rules = json.loads(rules_path.read_text(encoding="utf-8"))
            assert "categories" in rules
            assert len(rules["categories"]) > 0
