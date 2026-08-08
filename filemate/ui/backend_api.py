"""BackendAPI - FileMate 后端统一入口。

这是推荐的 API，用于 Gradio UI 调用。

用法::

    from filemate.ui.backend_api import BackendAPI

    # 单文件处理
    api = BackendAPI()
    session = api.process_file("/path/to/file.docx")
    print(session.suggested_name)

    # 批量处理
    sessions = api.process_files(["/path/a.docx", "/path/b.pdf"])

    # 查询历史
    history = api.list_sessions(status="done", limit=50)

    # 用户确认
    api.confirm(session_id, accepted=True, edits={"suggested_name": "新名字"})

"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from filemate.core.session import ProcessingSession, SessionStatus
from filemate.study import StudyService

logger = logging.getLogger(__name__)


class BackendAPI:
    """FileMate 后端 API - 统一入口。

    提供同步处理、查询、确认三大类方法。
    所有方法都是自包含的，不需要外部初始化。
    """

    def __init__(self, db_path: str = "filemate.db") -> None:
        """
        Parameters
        ----------
        db_path : str
            SQLite 数据库路径。默认 "filemate.db"。
        """
        self.db_path = db_path

    # =========================================================================
    # 处理
    # =========================================================================

    def process_file(
        self,
        file_path: str,
        *,
        skip_calendar: bool = False,
    ) -> ProcessingSession:
        """同步处理单个文件（推荐入口）。

        Parameters
        ----------
        file_path : str
            待处理文件的路径（绝对或相对路径）。
        skip_calendar : bool, optional
            是否跳过 .ics 日历生成。默认 False。

        Returns
        -------
        ProcessingSession
            处理后的会话对象，包含以下属性：

            =============== ==========================================
            属性            说明
            =============== ==========================================
            session_id      会话 ID（12 位十六进制）
            source_path     原始文件路径
            category        分类结果（如 "作业"、"课件"）
            confidence      置信度（0.0-1.0）
            suggested_name 建议的文件名
            entities        提取的实体（dict）
            milestones      识别的时间节点（list[dict]）
            error           错误信息（空字符串表示成功）
            =============== ==========================================

        Raises
        ------
        FileNotFoundError
            文件不存在时抛出。
        RuntimeError
            处理过程中发生其他错误时抛出。
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        try:
            session = _process_single_sync(
                str(path),
                skip_calendar=skip_calendar,
                db_path=self.db_path,
            )
            logger.info("process_file: %s -> session %s", path.name, session.session_id)
            return session
        except Exception as exc:
            logger.error("process_file 失败: %s", exc)
            raise RuntimeError(f"处理失败: {exc}") from exc

    def process_files(
        self,
        file_paths: list[str],
        *,
        skip_calendar: bool = False,
    ) -> list[ProcessingSession]:
        """批量处理多个文件。

        Parameters
        ----------
        file_paths : list[str]
            待处理文件的路径列表。
        skip_calendar : bool, optional
            是否跳过 .ics 日历生成。默认 False。

        Returns
        -------
        list[ProcessingSession]
            处理后的会话对象列表（顺序与输入一致）。
            处理失败的文件会返回一个 status='failed' 的 session。
        """
        results = []
        for path in file_paths:
            try:
                session = self.process_file(path, skip_calendar=skip_calendar)
                results.append(session)
            except Exception as exc:
                logger.warning("处理失败（%s）: %s", path, exc)
                # 创建失败的 session，保持与成功时相同的结构
                session = ProcessingSession(
                    session_id=uuid.uuid4().hex[:12],
                    source_path=str(path),
                    status=SessionStatus.FAILED,
                    error=str(exc),
                )
                results.append(session)
        return results

    # =========================================================================
    # 查询
    # =========================================================================

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """从数据库读取 session 详情。

        Parameters
        ----------
        session_id : str
            会话 ID。

        Returns
        -------
        dict or None
            会话详情字典，不存在则返回 None。
        """
        from filemate.execution.storage import SQLiteStorage

        storage = SQLiteStorage(self.db_path)
        storage.init_schema()  # 幂等
        session = storage.get_session(session_id)
        if session:
            # 反序列化 entities 和 milestones
            entities = session.get("entities")
            if isinstance(entities, str):
                try:
                    session["entities"] = json.loads(entities)
                except json.JSONDecodeError:
                    session["entities"] = {}
            else:
                session["entities"] = entities or {}

            milestones = session.get("milestones")
            if isinstance(milestones, str):
                try:
                    session["milestones"] = json.loads(milestones)
                except json.JSONDecodeError:
                    session["milestones"] = []
            else:
                session["milestones"] = milestones or []

        return session

    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """列出 session 列表。

        Parameters
        ----------
        status : str, optional
            按状态过滤（pending/processing/done/confirmed/skipped/failed）。
            不指定则返回所有状态。
        limit : int, optional
            返回数量上限。默认 100。

        Returns
        -------
        list[dict]
            会话详情字典列表（按创建时间降序）。
        """
        from filemate.execution.storage import SQLiteStorage

        storage = SQLiteStorage(self.db_path)
        storage.init_schema()
        return storage.list_sessions(status=status, limit=limit)

    def get_operations(self, session_id: str) -> list[dict[str, Any]]:
        """获取指定 session 的操作日志。

        Parameters
        ----------
        session_id : str
            会话 ID。

        Returns
        -------
        list[dict]
            操作日志列表（按时间升序）。
        """
        from filemate.execution.storage import SQLiteStorage

        storage = SQLiteStorage(self.db_path)
        storage.init_schema()
        return storage.get_operations(session_id)

    # =========================================================================
    # 确认 / 拒绝
    # =========================================================================

    def confirm(
        self,
        session_id: str,
        accepted: bool,
        edits: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """用户确认或拒绝 AI 建议。

        Parameters
        ----------
        session_id : str
            会话 ID。
        accepted : bool
            True = 接受建议；False = 拒绝。
        edits : dict, optional
            用户修改的字段（如 {"category": "作业", "suggested_name": "..."}）。

        Returns
        -------
        dict
            结果字典，包含 ``ok`` 字段。
        """
        from filemate.execution.storage import SQLiteStorage

        storage = SQLiteStorage(self.db_path)
        storage.init_schema()

        session = storage.get_session(session_id)
        if not session:
            return {"error": f"session 不存在: {session_id}", "ok": False}

        # 构建更新
        updates: dict[str, Any] = {}
        if edits:
            updates.update(edits)

        if accepted:
            updates["status"] = "confirmed"
        else:
            updates["status"] = "skipped"

        storage.update_session(session_id, **updates)
        storage.log_operation(
            session_id,
            "confirm" if accepted else "reject",
            detail=str(edits or {}),
        )

        logger.info("confirm: session %s accepted=%s", session_id, accepted)
        return {"ok": True, "session_id": session_id, "accepted": accepted}

    # =========================================================================
    # 文件出题与错题本
    # =========================================================================

    def _study(self) -> StudyService:
        return StudyService(db_path=self.db_path)

    def upload_study_file(self, file_path: str) -> dict[str, Any]:
        """上传学习资料。"""
        return self._study().upload_file(file_path)

    def list_study_documents(self) -> list[dict[str, Any]]:
        return self._study().list_documents()

    def delete_study_document(self, document_id: int) -> bool:
        return self._study().delete_document(document_id)

    def cleanup_study_documents(self) -> int:
        return self._study().cleanup_expired_documents()

    def parse_study_document(self, document_id: int) -> dict[str, Any]:
        return self._study().parse_document(document_id)

    def analyze_study_document(self, document_id: int) -> dict[str, Any]:
        return self._study().analyze_document(document_id)

    def generate_study_questions(
        self,
        document_id: int,
        plan: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return self._study().generate_file_questions(document_id, plan)

    def list_study_questions(self) -> list[dict[str, Any]]:
        return self._study().list_questions()

    def get_study_question(self, question_id: int) -> dict[str, Any] | None:
        return self._study().get_question(question_id)

    def generate_more_study_questions(
        self, question_id: int, count: int = 3
    ) -> list[dict[str, Any]]:
        return self._study().generate_more_questions(question_id, count=count)

    def submit_study_answer(
        self, question_id: int, user_answer: str
    ) -> dict[str, Any]:
        return self._study().submit_answer(question_id, user_answer)

    def list_study_wrong_book(self) -> list[dict[str, Any]]:
        return self._study().list_wrong_book()

    def list_study_due_reviews(self) -> list[dict[str, Any]]:
        return self._study().list_due_reviews()

    def review_study_wrong_item(self, item_id: int) -> dict[str, Any]:
        return self._study().review_wrong_item(item_id)

    def master_study_wrong_item(self, item_id: int) -> dict[str, Any]:
        return self._study().master_wrong_item(item_id)

    def favorite_study_question(
        self, question_id: int, is_favorite: bool
    ) -> bool:
        return self._study().favorite_question(question_id, is_favorite)

    def delete_study_question(self, question_id: int) -> bool:
        return self._study().delete_question(question_id)


# =========================================================================
# 私有实现：同步处理核心逻辑
# =========================================================================

def _process_single_sync(
    path: str,
    *,
    skip_calendar: bool = False,
    db_path: str = "filemate.db",
) -> ProcessingSession:
    """同步处理单个文件（私有实现）。"""
    from filemate.llm_client import LLMClient, LLMConfig
    from filemate.perception import FileParser
    from filemate.understanding import (
        Classifier,
        EntityExtractor,
        MilestoneDetector,
        Namer,
    )
    from filemate.execution.scheduler import CalendarBuilder, CalendarEvent
    from filemate.execution.file_ops import FileOps
    from filemate.execution.archiver import Archiver
    from filemate.execution.storage import SQLiteStorage

    # 初始化存储（确保数据库表存在）
    storage = SQLiteStorage(db_path)
    storage.init_schema()

    # 初始化各模块
    llm_config = LLMConfig.from_env()
    llm = LLMClient(llm_config)
    parser = FileParser()
    classifier = Classifier(llm)
    extractor = EntityExtractor(llm)
    detector = MilestoneDetector(llm)
    namer = Namer(llm)
    calendar = CalendarBuilder()
    file_ops = FileOps()
    archiver = Archiver(Path(".").resolve() / "archive", file_ops)

    # 构造 session
    session_id = uuid.uuid4().hex[:12]
    session = ProcessingSession(session_id=session_id, source_path=path)
    storage.create_session(session_id, path)

    # 阶段链
    stages = _build_stages(
        parser, classifier, extractor, detector, namer,
        calendar, archiver, storage, llm,
        skip_calendar=skip_calendar,
    )

    # 执行每个阶段
    for stage in stages:
        session = stage(session)
        if session.status.value == "failed":
            break

    # 保存最终状态
    storage.update_session(session_id, **session.to_dict())
    return session


def _build_stages(
    parser,
    classifier,
    extractor,
    detector,
    namer,
    calendar,
    archiver,
    storage,
    llm,
    *,
    skip_calendar: bool = False,
):
    """构造阶段链（与 main.py 保持一致）。"""
    stages = []

    # 阶段 1：解析文件
    def parse(session: ProcessingSession) -> ProcessingSession:
        parsed = parser.parse(session.source_path)
        session.entities["raw_text"] = parsed.get("raw_text", "")
        session.entities["metadata"] = parsed.get("metadata", {})
        storage.log_operation(session.session_id, "parse", session.source_path)
        return session

    parse.__name__ = "parse"
    stages.append(parse)

    # 阶段 2：分类
    def classify(session: ProcessingSession) -> ProcessingSession:
        raw_text = session.entities.get("raw_text", "")
        filename = Path(session.source_path).name
        result = classifier.classify(raw_text, filename=filename)
        session.category = result.get("category", "待确认")
        session.confidence = float(result.get("confidence", 0.0))
        if result.get("course_name"):
            session.entities["course_name"] = result["course_name"]
        storage.log_operation(
            session.session_id, "classify", f"{session.category}({session.confidence:.0%})"
        )
        return session

    classify.__name__ = "classify"
    stages.append(classify)

    # 阶段 3：实体抽取
    def extract(session: ProcessingSession) -> ProcessingSession:
        raw_text = session.entities.get("raw_text", "")
        entities = extractor.extract(raw_text)
        session.entities.update(entities)
        storage.log_operation(session.session_id, "extract")
        return session

    extract.__name__ = "extract"
    stages.append(extract)

    # 阶段 4：多里程碑识别
    def detect_milestones(session: ProcessingSession) -> ProcessingSession:
        raw_text = session.entities.get("raw_text", "")
        milestones = detector.detect(raw_text)
        session.milestones = milestones
        storage.log_operation(
            session.session_id, "detect_milestones", f"{len(milestones)} events"
        )
        return session

    detect_milestones.__name__ = "detect_milestones"
    stages.append(detect_milestones)

    # 阶段 5：生成文件名
    def generate_name(session: ProcessingSession) -> ProcessingSession:
        course = session.entities.get("course_name") or "未分类"
        task = session.entities.get("task_description") or Path(session.source_path).stem
        deadline = session.entities.get("deadline") or ""
        suggested = namer.generate(
            category=session.category,
            course=course,
            task=task,
            deadline=deadline,
            status="待处理",
        )
        session.suggested_name = suggested
        storage.log_operation(session.session_id, "name", suggested)
        return session

    generate_name.__name__ = "generate_name"
    stages.append(generate_name)

    # 阶段 6：日历（可选）
    if not skip_calendar:

        def calendar_(session: ProcessingSession) -> ProcessingSession:
            events = []
            for m in session.milestones:
                events.append(
                    CalendarEvent(
                        summary=f"[{session.category}] {m.get('event', '')}",
                        start=m.get("date", ""),
                        description=f"来源: {Path(session.source_path).name}",
                    )
                )
            if events:
                out = Path(session.source_path).with_suffix(".ics")
                calendar.save(events, out)
                session.entities["ics_path"] = str(out)
                storage.log_operation(session.session_id, "calendar", str(out))
            return session

        calendar_.__name__ = "calendar"
        stages.append(calendar_)

    # 阶段 7：归档（占位，后续确认层实现）

    return stages
