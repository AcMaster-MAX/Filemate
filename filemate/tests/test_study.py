"""文件出题与错题本单元测试。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from filemate.study import (
    REVIEW_INTERVALS,
    StudyService,
    check_answer,
    chunk_text,
    next_review_date_str,
    review_stage_after,
)
from filemate.study.generator import (
    analyze_document_with_llm,
    generate_questions_with_llm,
)


class TestChunkText:
    def test_empty_text(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("   \n  ") == []

    def test_short_text_single_chunk(self) -> None:
        chunks = chunk_text("第一段\n第二段")
        assert len(chunks) == 1
        assert "第一段" in chunks[0]

    def test_long_paragraph_split(self) -> None:
        text = "甲" * 900
        chunks = chunk_text(text, chunk_size=800, overlap=100)
        assert len(chunks) >= 2
        assert chunks[0] == "甲" * 800


class TestQuestionGenerator:
    def test_analyze_without_llm_raises(self) -> None:
        with pytest.raises(RuntimeError, match="AI 分析失败"):
            analyze_document_with_llm(None, "test.md", ["a", "b", "c"])

    def test_generate_without_llm_raises(self) -> None:
        with pytest.raises(RuntimeError, match="AI 出题失败"):
            generate_questions_with_llm(None, "数学", "线性代数", count=3)

    def test_generate_with_stub_llm(self) -> None:
        def fake_llm(**kwargs):
            return [
                {
                    "subject": "数学",
                    "knowledge_point": "线性代数",
                    "question_type": "choice",
                    "stem": "矩阵乘法满足什么性质？",
                    "options": ["A. 结合律", "B. 交换律"],
                    "answer": "A",
                    "analysis": "矩阵乘法满足结合律。",
                }
            ]

        questions = generate_questions_with_llm(
            fake_llm, "数学", "线性代数", count=3, question_type="choice"
        )
        assert len(questions) == 1
        assert questions[0]["stem"].startswith("矩阵乘法")


class TestCheckAnswer:
    def test_choice_answer(self) -> None:
        question = {"question_type": "choice", "answer": "A"}
        assert check_answer(question, "A")
        assert not check_answer(question, "B")

    def test_fill_answer_contains(self) -> None:
        question = {"question_type": "fill", "answer": "线性表"}
        assert check_answer(question, "线性表")
        assert check_answer(question, "数据结构中的线性表")
        assert not check_answer(question, "树")

    def test_short_answer_keyword_match(self) -> None:
        question = {"question_type": "short_answer", "answer": "栈 先进后出 线性"}
        assert check_answer(question, "栈是一种先进后出的线性结构")
        assert not check_answer(question, "完全无关")


class TestReviewSchedule:
    def test_intervals(self) -> None:
        assert REVIEW_INTERVALS == {1: 1, 2: 3, 3: 7, 4: 15, 5: 30}

    def test_stage_after(self) -> None:
        assert review_stage_after(1) == 2
        assert review_stage_after(5) == 5

    def test_next_review_date(self) -> None:
        today = date(2026, 8, 8)
        assert next_review_date_str(1, today) == "2026-08-09"
        assert next_review_date_str(2, today) == "2026-08-11"


class TestStudyServiceIntegration:
    def test_full_flow(self, tmp_path: Path) -> None:
        db_path = tmp_path / "study.db"
        upload_dir = tmp_path / "uploads"
        sample = tmp_path / "sample.txt"
        sample.write_text(
            "第一章 数据结构\n栈是先进后出。\n队列是先进先出。\n"
            "第二章 树\n二叉树有前序、中序、后序三种遍历。",
            encoding="utf-8",
        )

        class FakeLLM:
            def call_structured(self, prompt="", messages=None, **kwargs):
                if "文档分析专家" in prompt:
                    return {
                        "knowledge_points": 2,
                        "completeness": "rich",
                        "message": "分析完成",
                        "menu": [
                            {"question_type": "choice", "count": 2},
                            {"question_type": "short_answer", "count": 1},
                        ],
                    }
                user_text = (messages or [{}])[-1].get("content", "")
                count_match = re.search(r"数量：(\d+)", user_text)
                type_match = re.search(r"题型：(\w+)", user_text)
                count = int(count_match.group(1)) if count_match else 1
                question_type = type_match.group(1) if type_match else "choice"
                return [
                    {
                        "subject": "数据结构",
                        "knowledge_point": "树",
                        "question_type": question_type,
                        "stem": f"{question_type} 测试题 {i}",
                        "options": ["A. 对", "B. 错"] if question_type == "choice" else [],
                        "answer": "A" if question_type == "choice" else "树",
                        "analysis": "测试解析",
                    }
                    for i in range(count)
                ]

        service = StudyService(db_path=str(db_path), upload_dir=str(upload_dir))
        service._llm = lambda: FakeLLM()  # type: ignore[method-assign]

        doc = service.upload_file(sample)
        assert doc["id"] > 0
        assert doc["filename"] == "sample.txt"

        parsed = service.parse_document(doc["id"])
        assert parsed["ok"] is True
        assert parsed["chunks"] >= 1

        menu = service.analyze_document(doc["id"])
        assert menu["menu"]

        questions = service.generate_file_questions(
            doc["id"],
            [
                {"question_type": "choice", "count": 2},
                {"question_type": "short_answer", "count": 1},
            ],
        )
        assert len(questions) == 3

        result = service.submit_answer(questions[0]["id"], "B")
        assert result["is_correct"] is False
        wrong_book = service.list_wrong_book()
        assert len(wrong_book) == 1
        assert wrong_book[0]["question_id"] == questions[0]["id"]

        item_id = wrong_book[0]["id"]
        reviewed = service.review_wrong_item(item_id)
        assert reviewed["review_stage"] == 2
        assert reviewed["next_review_date"] >= date.today().isoformat()

        mastered = service.master_wrong_item(item_id)
        assert mastered["mastered"] == 1
        assert service.list_due_reviews() == []

    def test_correct_answer_not_added_to_wrong_book(self, tmp_path: Path) -> None:
        db_path = tmp_path / "study.db"
        service = StudyService(db_path=str(db_path), upload_dir=str(tmp_path / "uploads"))
        service._llm = lambda: None  # type: ignore[method-assign]

        question_id = service.storage.save_questions([
            {
                "user_id": "local",
                "document_id": None,
                "subject": "数学",
                "knowledge_point": "测试",
                "question_type": "choice",
                "stem": "1+1=?",
                "options_json": "[\"A. 1\", \"B. 2\"]",
                "answer": "B",
                "analysis": "",
                "source": "test",
            }
        ])[0]

        result = service.submit_answer(question_id, "B")
        assert result["is_correct"] is True
        assert service.list_wrong_book() == []

    def test_delete_document_and_cleanup(self, tmp_path: Path) -> None:
        db_path = tmp_path / "study.db"
        upload_dir = tmp_path / "uploads"
        sample = tmp_path / "sample.txt"
        sample.write_text("测试文档内容。", encoding="utf-8")

        service = StudyService(db_path=str(db_path), upload_dir=str(upload_dir))
        doc = service.upload_file(sample)
        document_id = doc["id"]
        storage_path = doc["storage_path"]
        assert Path(storage_path).exists()

        assert service.delete_document(document_id) is True
        assert service.list_documents() == []
        assert not Path(storage_path).exists()

        doc2 = service.upload_file(sample)
        assert service.storage.update_study_document(
            doc2["id"], temp_cleanup_at="2020-01-01"
        )
        assert service.cleanup_expired_documents() == 1
        assert service.list_documents() == []

    def test_favorite_and_delete_question(self, tmp_path: Path) -> None:
        service = StudyService(db_path=str(tmp_path / "study.db"), upload_dir=str(tmp_path / "uploads"))
        question_id = service.storage.save_questions([
            {
                "user_id": "local",
                "document_id": None,
                "subject": "数学",
                "knowledge_point": "测试",
                "question_type": "choice",
                "stem": "1+1=?",
                "options_json": "[\"A. 1\", \"B. 2\"]",
                "answer": "B",
                "analysis": "",
                "source": "test",
            }
        ])[0]

        assert service.favorite_question(question_id, True) is True
        question = service.get_question(question_id)
        assert question is not None
        assert question["is_favorite"] == 1

        assert service.delete_question(question_id) is True
        assert service.get_question(question_id) is None
