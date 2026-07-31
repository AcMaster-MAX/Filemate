"""命名生成模块单元测试。

全部用 _Stub 假 LLM，不产生真实 API 调用，CI 可直接跑。
"""
from __future__ import annotations

import re

import pytest

from filemate.understanding.namer import Namer

# 命名规范：[课程]-[类型]-[任务]-[截止]-[状态]，五段方括号，段内不得再有方括号
NAME_PATTERN = re.compile(
    r"^\[[^\[\]]+\]-\[[^\[\]]+\]-\[[^\[\]]+\]-\[[^\[\]]+\]-\[[^\[\]]+\]$"
)

VALID_CATEGORIES = {"课件", "作业", "竞赛通知", "考试通知", "参考资料", "大创通知", "待确认"}

MAX_LEN = 80  # 与 namer._MAX_LEN 对齐


class _Stub:
    """假 LLM 客户端。call 用于 task 精简，refined 为 None 时抛异常。"""

    def __init__(self, refined: str | None = "精简后任务") -> None:
        self.refined = refined
        self.calls = 0

    def call(self, prompt="", **kw) -> str:
        self.calls += 1
        if self.refined is None:
            raise RuntimeError("API 超时")
        return self.refined

    def call_structured(self, prompt="", messages=None, **kw):
        return {}


def _make_namer(refined: str | None = "精简后任务") -> tuple[Namer, _Stub]:
    stub = _Stub(refined)
    return Namer(stub), stub


class TestNamerNormal:
    """正常生成。"""

    def test_basic_name(self) -> None:
        namer, stub = _make_namer()
        name = namer.generate(
            category="作业", course="操作系统", task="实验三",
            deadline="2026-04-15", status="待处理",
        )
        assert name == "[操作系统]-[作业]-[实验三]-[0415]-[待处理]"
        assert stub.calls == 0, "task 未超长不该调用 LLM"

    def test_matches_pattern(self) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category="课件", course="高等数学", task="第十章曲线积分",
            deadline="2026-06-01",
        )
        assert NAME_PATTERN.match(name), f"格式不符: {name}"

    def test_default_status(self) -> None:
        """status 不传时默认"待处理"。"""
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course="操作系统", task="实验三", deadline="",
        )
        assert name.endswith("-[待处理]")


class TestNamerCategory:
    """category 归一化。"""

    @pytest.mark.parametrize("category", sorted(VALID_CATEGORIES))
    def test_valid_category_kept(self, category: str) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category=category, course="操作系统", task="实验三", deadline="",
        )
        assert f"]-[{category}]-[" in name

    @pytest.mark.parametrize("bad", ["垃圾分类", "homework", "", "未知类型", "笔记"])
    def test_invalid_category_normalized(self, bad: str) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category=bad, course="操作系统", task="实验三", deadline="",
        )
        assert name == "[操作系统]-[待确认]-[实验三]-[待定]-[待处理]"


class TestNamerDefaults:
    """空字段用默认值。"""

    def test_all_empty_fields(self) -> None:
        namer, _ = _make_namer()
        name = namer.generate(category="作业", course="", task="", deadline="", status="")
        assert name == "[未分类]-[作业]-[未命名]-[待定]-[待处理]"

    @pytest.mark.parametrize("blank", ["", "   ", "\n", "\t "])
    def test_whitespace_only_treated_as_empty(self, blank: str) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course=blank, task=blank, deadline=blank, status=blank,
        )
        assert name == "[未分类]-[作业]-[未命名]-[待定]-[待处理]"


class TestNamerDeadline:
    """截止日期格式化。"""

    def test_iso_date_to_mmdd(self) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course="操作系统", task="实验三", deadline="2026-04-15",
        )
        assert "]-[0415]-[" in name

    def test_mmdd_passthrough(self) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course="操作系统", task="实验三", deadline="0415",
        )
        assert "]-[0415]-[" in name

    def test_empty_deadline_becomes_placeholder(self) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course="操作系统", task="实验三", deadline="",
        )
        assert "]-[待定]-[" in name


class TestNamerSanitize:
    """非法字符清洗。"""

    def test_brackets_stripped(self) -> None:
        """用户输入自带方括号时必须去掉，否则文件名嵌套括号解析不了。"""
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course="[操作系统]", task="[实验三]", deadline="0415",
        )
        assert name == "[操作系统]-[作业]-[实验三]-[0415]-[待处理]"
        assert NAME_PATTERN.match(name)

    def test_newline_collapsed(self) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course="操作\n系统", task="实验\r三", deadline="0415",
        )
        assert name == "[操作 系统]-[作业]-[实验 三]-[0415]-[待处理]"

    def test_multiple_spaces_collapsed(self) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course="操作    系统", task="实验三", deadline="0415",
        )
        assert "[操作 系统]" in name


class TestNamerTruncation:
    """超长处理。"""

    def test_long_name_truncated(self) -> None:
        namer, _ = _make_namer()
        name = namer.generate(
            category="作业", course="计算机科学与技术专业" * 8, task="实验三",
            deadline="0415",
        )
        assert len(name) <= MAX_LEN, f"文件名超长 ({len(name)}): {name}"
        assert NAME_PATTERN.match(name), f"截断后格式被破坏: {name}"

    def test_long_task_refined_by_llm(self) -> None:
        """task 超 15 字应调 LLM 精简。"""
        namer, stub = _make_namer(refined="第三章课后习题")
        name = namer.generate(
            category="作业", course="高等数学",
            task="请同学们在本周五之前完成第三章的全部课后习题并提交到学习通平台",
            deadline="0415",
        )
        assert stub.calls == 1, "task 超长应触发一次 LLM 精简"
        assert "[第三章课后习题]" in name

    def test_llm_failure_falls_back_to_hard_truncate(self) -> None:
        """LLM 精简失败时硬截断到 15 字，不应抛异常。"""
        long_task = "请同学们在本周五之前完成第三章的全部课后习题并提交到学习通平台"
        namer, stub = _make_namer(refined=None)  # refined=None → call 抛异常
        name = namer.generate(
            category="作业", course="高等数学", task=long_task, deadline="0415",
        )
        assert stub.calls == 1
        assert f"[{long_task[:15]}]" in name
        assert NAME_PATTERN.match(name)

    @pytest.mark.parametrize("bad_refined", ["", "太长了" * 10, "短"])
    def test_unusable_refine_result_falls_back(self, bad_refined: str) -> None:
        """LLM 返回空/超长/过短（不在 2-15 字区间）时回落硬截断。"""
        long_task = "请同学们在本周五之前完成第三章的全部课后习题并提交到学习通平台"
        namer, _ = _make_namer(refined=bad_refined)
        name = namer.generate(
            category="作业", course="高等数学", task=long_task, deadline="0415",
        )
        assert f"[{long_task[:15]}]" in name
