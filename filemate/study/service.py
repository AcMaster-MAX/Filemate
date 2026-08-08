"""StudyService：文件出题与错题本的门面服务。"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filemate.execution.storage import SQLiteStorage
from filemate.perception import FileParser, OCRBackend

from .generator import (
    analyze_document_with_llm,
    check_answer,
    chunk_text,
    generate_questions_with_llm,
)
from .scheduling import next_review_date_str, review_stage_after

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".pdf", ".docx", ".pptx", ".txt", ".md", ".png", ".jpg", ".jpeg"}
MAX_FILES_PER_USER = 5
MAX_TOTAL_BYTES = 50 * 1024 * 1024


class StudyService:
    """文件出题 + 错题本。当前为单用户本地模式，user_id 预留。"""

    def __init__(
        self,
        db_path: str = "filemate.db",
        upload_dir: str | Path | None = None,
        user_id: str = "local",
    ) -> None:
        self.db_path = db_path
        self.upload_dir = Path(
            upload_dir or os.getenv("FILEMATE_UPLOAD_DIR", "uploads")
        )
        self.user_id = user_id
        self._storage: SQLiteStorage | None = None

    @property
    def storage(self) -> SQLiteStorage:
        if self._storage is None:
            self._storage = SQLiteStorage(self.db_path)
            self._storage.init_schema()
        return self._storage

    def _llm(self):
        """懒加载 LLM；未配置 API Key 时返回 None，走离线兜底。"""
        try:
            from filemate.core.registry import get_registry
            return get_registry().get_llm()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 文件上传与解析
    # ------------------------------------------------------------------

    def upload_file(self, file_path: str | Path) -> dict[str, Any]:
        src = Path(file_path)
        if not src.is_file():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        suffix = src.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"仅支持: {sorted(ALLOWED_SUFFIXES)}")

        documents = self.storage.list_study_documents(self.user_id)
        if len(documents) >= MAX_FILES_PER_USER:
            raise ValueError(f"最多同时保存 {MAX_FILES_PER_USER} 个文件")
        size = src.stat().st_size
        total = sum(int(d.get("size_bytes") or 0) for d in documents) + size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("文件总大小超过 50MB 限制")

        user_dir = self.upload_dir / self.user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        dest = user_dir / f"{uuid.uuid4().hex}{suffix}"
        shutil.copy2(str(src), str(dest))
        self.cleanup_expired_documents()

        document_id = self.storage.create_study_document(
            user_id=self.user_id,
            filename=src.name,
            file_type=suffix.lstrip("."),
            storage_path=str(dest),
            size_bytes=size,
            temp_cleanup_at=(datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat(),
        )
        logger.info("文件上传: id=%s name=%s", document_id, src.name)
        return self.storage.get_study_document(document_id, self.user_id) or {}

    def list_documents(self) -> list[dict[str, Any]]:
        return self.storage.list_study_documents(self.user_id)

    def delete_document(self, document_id: int) -> bool:
        """删除文档记录、切片、分析结果和本地文件。"""
        doc = self.storage.get_study_document(document_id, self.user_id)
        if doc is None:
            raise ValueError("文档不存在")
        deleted = self.storage.delete_study_document(document_id, self.user_id)
        path = Path(doc["storage_path"])
        if path.exists():
            try:
                path.unlink()
            except OSError:
                logger.warning("文档文件删除失败: %s", path)
        logger.info("文档已删除: id=%s", document_id)
        return deleted

    def cleanup_expired_documents(self) -> int:
        """清理超过 7 天的临时文档，返回删除数量。"""
        expired = self.storage.list_expired_documents(
            self.user_id, date.today().isoformat()
        )
        count = 0
        for doc in expired:
            try:
                self.delete_document(doc["id"])
                count += 1
            except Exception:
                logger.exception("过期文档清理失败: id=%s", doc.get("id"))
        if count:
            logger.info("已清理 %d 个过期文档", count)
        return count

    def parse_document(self, document_id: int) -> dict[str, Any]:
        doc = self.storage.get_study_document(document_id, self.user_id)
        if doc is None:
            raise ValueError("文档不存在")

        file_type = doc.get("file_type", "")
        raw_text = ""
        if file_type in {"txt", "md"}:
            raw_text = Path(doc["storage_path"]).read_text(encoding="utf-8", errors="ignore")
        elif file_type in {"png", "jpg", "jpeg"}:
            raw_text = OCRBackend().recognize(doc["storage_path"])
        else:
            parsed = FileParser().parse(doc["storage_path"])
            raw_text = parsed.get("raw_text", "") or ""
            if not raw_text.strip() and file_type == "pdf":
                raw_text = OCRBackend().recognize(doc["storage_path"])
        if not raw_text.strip():
            return {"ok": False, "document_id": document_id, "message": "未能从文档中提取文本"}

        chunks = chunk_text(raw_text)
        if not chunks:
            return {"ok": False, "document_id": document_id, "message": "文本切片为空"}

        self.storage.delete_knowledge_chunks(document_id)
        self.storage.add_knowledge_chunks(document_id, chunks)
        self.storage.update_study_document(
            document_id, status="parsed", chunks_count=len(chunks)
        )
        logger.info("文档解析: id=%s chunks=%d", document_id, len(chunks))
        return {
            "ok": True,
            "document_id": document_id,
            "chunks": len(chunks),
            "message": "解析完成",
        }

    def analyze_document(self, document_id: int) -> dict[str, Any]:
        doc = self.storage.get_study_document(document_id, self.user_id)
        if doc is None:
            raise ValueError("文档不存在")
        chunks = self.storage.get_knowledge_chunks(document_id, limit=12)
        if not chunks:
            raise ValueError("文档尚未解析")

        llm = self._llm()
        result = analyze_document_with_llm(
            llm.call_structured if llm else None,
            doc.get("filename", ""),
            [c["content"] for c in chunks],
        )
        self.storage.save_file_analyze_result(
            document_id,
            json.dumps(result, ensure_ascii=False),
            result.get("message", ""),
        )
        return result

    # ------------------------------------------------------------------
    # 出题
    # ------------------------------------------------------------------

    def generate_file_questions(
        self,
        document_id: int,
        plan: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        doc = self.storage.get_study_document(document_id, self.user_id)
        if doc is None:
            raise ValueError("文档不存在")
        chunks = self.storage.get_knowledge_chunks(document_id)
        if not chunks:
            raise ValueError("文档尚未解析")

        context = [c["content"] for c in chunks]
        subject, knowledge_point = self._document_profile(doc, chunks)
        llm = self._llm()
        questions: list[dict[str, Any]] = []
        for item in plan or []:
            qtype = str(item.get("question_type", "choice")).strip()
            count = int(item.get("count", 1) or 1)
            questions.extend(
                generate_questions_with_llm(
                    llm.call_structured if llm else None,
                    subject=subject,
                    knowledge_point=knowledge_point,
                    count=count,
                    question_type=qtype,
                    context=context,
                )
            )
        return self._save_questions(questions, document_id=document_id)

    def _document_profile(
        self,
        doc: dict[str, Any],
        chunks: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """用理解层提取课程/知识点，失败时回退到文件名。"""
        subject = "综合"
        knowledge_point = Path(doc["filename"]).stem
        if not chunks:
            return subject, knowledge_point
        try:
            from filemate.understanding import Classifier, EntityExtractor

            llm = self._llm()
            text = "\n".join(c["content"] for c in chunks[:3])[:2000]
            classifier = Classifier(llm)
            extractor = EntityExtractor(llm)
            classification = classifier.classify(text, filename=doc.get("filename", ""))
            entities = extractor.extract(text)
            subject = (
                classification.get("course_name")
                or entities.get("course_name")
                or subject
            )
            knowledge_point = (
                entities.get("task_description")
                or classification.get("course_name")
                or knowledge_point
            )
        except Exception:
            logger.warning("文档课程/知识点提取失败，使用文件名兜底: %s", doc.get("filename"))
        return subject, knowledge_point

    def generate_more_questions(
        self,
        question_id: int,
        count: int = 3,
    ) -> list[dict[str, Any]]:
        question = self.storage.get_question(question_id, self.user_id)
        if question is None:
            raise ValueError("题目不存在")
        llm = self._llm()
        generated = generate_questions_with_llm(
            llm.call_structured if llm else None,
            subject=question["subject"],
            knowledge_point=question["knowledge_point"],
            count=count,
            question_type=question["question_type"],
            context=None,
        )
        return self._save_questions(generated, document_id=question.get("document_id"))

    def list_questions(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.storage.list_questions(self.user_id, limit=limit)

    def get_question(self, question_id: int) -> dict[str, Any] | None:
        return self.storage.get_question(question_id, self.user_id)

    def favorite_question(self, question_id: int, is_favorite: bool) -> bool:
        return self.storage.set_question_favorite(
            question_id, self.user_id, 1 if is_favorite else 0
        )

    def delete_question(self, question_id: int) -> bool:
        return self.storage.delete_question(question_id, self.user_id)

    def _save_questions(
        self,
        questions: list[dict[str, Any]],
        *,
        document_id: int | None,
    ) -> list[dict[str, Any]]:
        rows = [
            {
                "user_id": self.user_id,
                "document_id": document_id,
                "subject": q.get("subject", ""),
                "knowledge_point": q.get("knowledge_point", ""),
                "question_type": q.get("question_type", "choice"),
                "stem": q.get("stem", ""),
                "options_json": json.dumps(q.get("options", []), ensure_ascii=False),
                "answer": q.get("answer", ""),
                "analysis": q.get("analysis", ""),
                "source": "ai",
            }
            for q in questions
        ]
        ids = self.storage.save_questions(rows)
        saved = []
        for question_id in ids:
            saved.append(self.storage.get_question(question_id, self.user_id) or {})
        return saved

    # ------------------------------------------------------------------
    # 作答与错题本
    # ------------------------------------------------------------------

    def submit_answer(
        self,
        question_id: int,
        user_answer: str,
        spent_seconds: int = 0,
    ) -> dict[str, Any]:
        question = self.storage.get_question(question_id, self.user_id)
        if question is None:
            raise ValueError("题目不存在")
        is_correct = check_answer(question, user_answer)
        self.storage.add_answer_record(
            self.user_id, question_id, user_answer, 1 if is_correct else 0, spent_seconds
        )

        if not is_correct:
            existing = self.storage.get_wrong_book_item(self.user_id, question_id)
            if existing is None:
                self.storage.add_wrong_book_item(
                    user_id=self.user_id,
                    question_id=question_id,
                    mistake_reason=user_answer,
                    next_review_date=next_review_date_str(1),
                )
            else:
                self.storage.update_wrong_book_item(
                    existing["id"], review_count=existing["review_count"] + 1
                )

        return {
            "question_id": question_id,
            "is_correct": is_correct,
            "correct_answer": question.get("answer", ""),
            "analysis": question.get("analysis", ""),
        }

    def list_wrong_book(self) -> list[dict[str, Any]]:
        return self.storage.list_wrong_book(self.user_id)

    def list_due_reviews(self) -> list[dict[str, Any]]:
        return self.storage.list_due_wrong_book(self.user_id, date.today().isoformat())

    def review_wrong_item(self, item_id: int) -> dict[str, Any]:
        item = self.storage.get_wrong_book_item_by_id(item_id, self.user_id)
        if item is None:
            raise ValueError("错题记录不存在")
        stage = review_stage_after(item["review_stage"])
        self.storage.update_wrong_book_item(
            item_id,
            review_count=item["review_count"] + 1,
            review_stage=stage,
            next_review_date=next_review_date_str(stage),
            last_reviewed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        return self.storage.get_wrong_book_item_by_id(item_id, self.user_id) or {}

    def master_wrong_item(self, item_id: int) -> dict[str, Any]:
        item = self.storage.get_wrong_book_item_by_id(item_id, self.user_id)
        if item is None:
            raise ValueError("错题记录不存在")
        self.storage.update_wrong_book_item(
            item_id,
            mastered=1,
            review_count=item["review_count"] + 1,
            last_reviewed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        return self.storage.get_wrong_book_item_by_id(item_id, self.user_id) or {}
