"""FileMate Gradio 界面 - 完整实现。

六个 Tab：
1. 导入：文件上传 + 文件列表
2. 分类预览：建议分类 + 置信度 + 确认/修改
3. 命名预览：原始名 vs 建议名 + 编辑
4. 日程预览：时间轴视图 + 导出 .ics
5. 文件出题：上传解析 + AI 分析 + 按组合出题
6. 错题本：答题判题 + 复习排期
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import gradio as gr

from filemate.core.session import ProcessingSession, SessionStatus
from filemate.ui.backend_api import BackendAPI
from filemate.execution.scheduler import CalendarBuilder, CalendarEvent

logger = logging.getLogger(__name__)


class FileMateUI:
    """FileMate Gradio 界面。

    用法::

        ui = FileMateUI()
        app = ui.build()
        app.launch()

    或直接使用便捷函数::

        app = create_app()
        app.launch()
    """

    def __init__(self) -> None:
        self._api = BackendAPI()

    # =====================================================================
    # Tab 1: 导入（文件上传 + 文件列表）
    # =====================================================================

    def process_file(self, file_path: str) -> tuple[str, str, str]:
        """处理上传的文件。"""
        if not file_path:
            return "", "", ""

        try:
            session = self._api.process_file(file_path)
            return (
                session.category or "待确认",
                f"{session.confidence:.0%}",
                session.suggested_name or "未生成",
            )
        except Exception as exc:
            logger.error("文件处理失败: %s", exc)
            return "错误", "0%", str(exc)

    def get_history(self) -> list[dict]:
        """获取历史记录。"""
        sessions = self._api.list_sessions(limit=20)
        result = []
        for s in sessions:
            result.append({
                "ID": s.get("session_id", ""),
                "文件": Path(s.get("source_path", "")).name,
                "分类": s.get("category", "待确认"),
                "状态": s.get("status", "unknown"),
            })
        return result

    # =====================================================================
    # Tab 2: 分类预览（建议分类 + 置信度 + 确认/修改）
    # =====================================================================

    def confirm_category(
        self,
        session_id: str,
        new_category: str,
    ) -> str:
        """确认或修改分类。"""
        result = self._api.confirm(
            session_id,
            accepted=True,
            edits={"category": new_category},
        )
        return "已确认" if result.get("ok") else "确认失败"

    # =====================================================================
    # Tab 3: 命名预览（原始名 vs 建议名 + 编辑）
    # =====================================================================

    def confirm_name(
        self,
        session_id: str,
        new_name: str,
    ) -> str:
        """确认或修改命名。"""
        result = self._api.confirm(
            session_id,
            accepted=True,
            edits={"suggested_name": new_name},
        )
        return "已确认" if result.get("ok") else "确认失败"

    # =====================================================================
    # Tab 4: 日程预览（时间轴视图 + 导出 .ics）
    # =====================================================================

    def get_milestones_view(self, session_id: str) -> tuple[str, str]:
        """获取日程时间轴视图。"""
        session = self._api.get_session(session_id)
        if not session:
            return "无数据", ""

        milestones = session.get("milestones", [])
        if not milestones:
            return "无里程碑", ""

        # 构建时间轴
        timeline_lines = []
        for m in milestones:
            date = m.get("date", "?")
            event = m.get("event", "?")
            timeline_lines.append(f"**{date}** - {event}")

        timeline = "\n\n".join(timeline_lines)

        # 生成 .ics
        ics_content = ""
        try:
            builder = CalendarBuilder()
            events = []
            for m in milestones:
                events.append(CalendarEvent(
                    summary=f"[{session.get('category', '待确认')}] {m.get('event', '')}",
                    start=m.get("date", ""),
                    description=f"来源: {Path(session.get('source_path', '')).name}",
                ))
            if events:
                ics_content = builder.build(events).decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.error("生成 .ics 失败: %s", exc)

        return timeline, ics_content

    # =====================================================================
    # Tab 5: 文件出题（上传 / 解析 / 分析 / 出题）
    # =====================================================================

    def upload_and_parse_study(self, file_path: str) -> tuple[str, str]:
        """上传学习资料并解析。"""
        if not file_path:
            return "", "请选择文件"
        try:
            doc = self._api.upload_study_file(file_path)
            document_id = doc.get("id")
            result = self._api.parse_study_document(document_id)
            return str(document_id), result.get("message", "解析失败")
        except Exception as exc:
            logger.error("上传解析失败: %s", exc)
            return "", str(exc)

    def get_study_documents_rows(self) -> list[list[str]]:
        """获取已上传文档列表。"""
        try:
            documents = self._api.list_study_documents()
        except Exception as exc:
            return [["错误", "", "", "", "", "", str(exc)]]
        return [
            [
                str(doc.get("id", "")),
                doc.get("filename", ""),
                doc.get("file_type", ""),
                doc.get("status", ""),
                str(doc.get("chunks_count", 0)),
                str(doc.get("size_bytes", 0)),
                doc.get("created_at", ""),
            ]
            for doc in documents
        ]

    def delete_study_document(self, document_id: str) -> str:
        """删除文档及其关联数据。"""
        if not document_id:
            return "请输入文档 ID"
        try:
            ok = self._api.delete_study_document(int(document_id))
        except Exception as exc:
            return f"删除失败: {exc}"
        return "已删除" if ok else "文档不存在或删除失败"

    def cleanup_study_documents(self) -> str:
        """清理超过 7 天的临时文档。"""
        try:
            count = self._api.cleanup_study_documents()
        except Exception as exc:
            return f"清理失败: {exc}"
        return f"已清理 {count} 个过期文档"

    def analyze_study_document(self, document_id: str) -> str:
        """AI 预分析文档并返回题型菜单。"""
        if not document_id:
            return "请输入文档 ID"
        try:
            result = self._api.analyze_study_document(int(document_id))
        except Exception as exc:
            return f"分析失败: {exc}"

        lines = [
            f"**知识点数量**：{result.get('knowledge_points', 0)}",
            f"**内容完整度**：{result.get('completeness', 'unknown')}",
            f"**说明**：{result.get('message', '')}",
            "",
            "**建议题型**：",
        ]
        for item in result.get("menu", []):
            lines.append(f"- {item.get('question_type')}: {item.get('count')} 题")
        return "\n".join(lines)

    def generate_study_questions(
        self,
        document_id: str,
        choice_count: float,
        fill_count: float,
        short_count: float,
    ) -> str:
        """按题型组合生成题目。"""
        if not document_id:
            return "请输入文档 ID"
        plan = [
            {"question_type": "choice", "count": int(choice_count or 0)},
            {"question_type": "fill", "count": int(fill_count or 0)},
            {"question_type": "short_answer", "count": int(short_count or 0)},
        ]
        plan = [item for item in plan if item["count"] > 0]
        if not plan:
            return "请至少选择一种题型"
        try:
            questions = self._api.generate_study_questions(int(document_id), plan)
        except Exception as exc:
            return f"出题失败: {exc}"
        if not questions:
            return "未生成题目"
        lines = []
        for index, q in enumerate(questions, 1):
            lines.append(f"**Q{index}. [{q.get('question_type')}] {q.get('stem')}**")
            options = q.get("options") or []
            if options:
                lines.append("  " + " | ".join(str(o) for o in options))
            lines.append(f"  答案：{q.get('answer', '')}")
            if q.get("analysis"):
                lines.append(f"  解析：{q['analysis']}")
            lines.append("")
        return "\n".join(lines)

    # =====================================================================
    # Tab 6: 错题本（作答 / 错题 / 复习）
    # =====================================================================

    def submit_study_answer(self, question_id: str, user_answer: str) -> str:
        """提交作答并自动沉淀错题。"""
        if not question_id:
            return "请输入题目 ID"
        try:
            result = self._api.submit_study_answer(int(question_id), user_answer or "")
        except Exception as exc:
            return f"作答失败: {exc}"
        status = "回答正确" if result.get("is_correct") else "回答错误，已加入错题本"
        lines = [f"**{status}**", "", f"正确答案：{result.get('correct_answer', '')}"]
        if result.get("analysis"):
            lines.append(f"解析：{result['analysis']}")
        return "\n".join(lines)

    def favorite_study_question(self, question_id: str) -> str:
        """收藏 / 取消收藏题目。"""
        if not question_id:
            return "请输入题目 ID"
        try:
            question = self._api.get_study_question(int(question_id))
            if question is None:
                return "题目不存在"
            is_favorite = not bool(question.get("is_favorite"))
            self._api.favorite_study_question(int(question_id), is_favorite)
        except Exception as exc:
            return f"操作失败: {exc}"
        return "已收藏" if is_favorite else "已取消收藏"

    def delete_study_question(self, question_id: str) -> str:
        """删除题目并清理作答与错题记录。"""
        if not question_id:
            return "请输入题目 ID"
        try:
            ok = self._api.delete_study_question(int(question_id))
        except Exception as exc:
            return f"删除失败: {exc}"
        return "已删除" if ok else "题目不存在或删除失败"

    def get_study_questions_rows(self) -> list[list[str]]:
        try:
            questions = self._api.list_study_questions()
        except Exception as exc:
            return [["错误", "", "", str(exc)]]
        return [
            [
                str(q.get("id", "")),
                q.get("question_type", ""),
                q.get("knowledge_point", ""),
                q.get("stem", ""),
            ]
            for q in questions
        ]

    def get_wrong_book_rows(self) -> list[list[str]]:
        try:
            items = self._api.list_study_wrong_book()
        except Exception as exc:
            return [["错误", "", "", "", "", "", str(exc)]]
        return [
            [
                str(item.get("id", "")),
                str(item.get("question_id", "")),
                item.get("knowledge_point", ""),
                str(item.get("review_stage", "")),
                item.get("next_review_date", ""),
                "已掌握" if item.get("mastered") else "复习中",
                item.get("question_stem", ""),
            ]
            for item in items
        ]

    def get_due_reviews_rows(self) -> list[list[str]]:
        try:
            items = self._api.list_study_due_reviews()
        except Exception as exc:
            return [["错误", "", "", "", str(exc)]]
        return [
            [
                str(item.get("id", "")),
                str(item.get("question_id", "")),
                item.get("knowledge_point", ""),
                item.get("next_review_date", ""),
                item.get("question_stem", ""),
            ]
            for item in items
        ]

    def review_study_wrong_item(self, item_id: str) -> str:
        if not item_id:
            return "请输入错题记录 ID"
        try:
            item = self._api.review_study_wrong_item(int(item_id))
        except Exception as exc:
            return f"复习失败: {exc}"
        return (
            f"已复习一次，当前阶段 {item.get('review_stage')}，"
            f"下次复习 {item.get('next_review_date')}"
        )

    def master_study_wrong_item(self, item_id: str) -> str:
        if not item_id:
            return "请输入错题记录 ID"
        try:
            item = self._api.master_study_wrong_item(int(item_id))
        except Exception as exc:
            return f"标记失败: {exc}"
        return f"已标记掌握，共复习 {item.get('review_count')} 次"

    def generate_more_study_questions(self, question_id: str) -> str:
        if not question_id:
            return "请输入题目 ID"
        try:
            questions = self._api.generate_more_study_questions(int(question_id), count=3)
        except Exception as exc:
            return f"举一反三失败: {exc}"
        lines = []
        for index, q in enumerate(questions, 1):
            lines.append(f"**Q{index}. [{q.get('question_type')}] {q.get('stem')}**")
            lines.append(f"  答案：{q.get('answer', '')}")
        return "\n".join(lines)

    # =====================================================================
    # 构建 UI
    # =====================================================================

    def build(self) -> gr.Blocks:
        """构建 Gradio 界面。"""

        with gr.Blocks(title="FileMate - 智能文件管理器") as app:
            gr.Markdown("# FileMate\n智能文件管理，助你梳理工作脉络")

            with gr.Tab("导入文件"):
                with gr.Row():
                    with gr.Column(scale=1):
                        file_input = gr.File(
                            label="上传文件",
                            file_count="single",
                            file_types=[".docx", ".pdf", ".pptx"],
                        )
                        process_btn = gr.Button("处理文件", variant="primary")

                    with gr.Column(scale=2):
                        category_output = gr.Textbox(label="分类结果")
                        confidence_output = gr.Textbox(label="置信度")
                        name_output = gr.Textbox(label="建议文件名")

                # 处理文件
                process_btn.click(
                    fn=self.process_file,
                    inputs=[file_input],
                    outputs=[category_output, confidence_output, name_output],
                )

            with gr.Tab("历史记录"):
                history_btn = gr.Button("刷新列表")
                history_table = gr.Dataframe(
                    headers=["ID", "文件", "分类", "状态"],
                    label="处理历史",
                )

                history_btn.click(
                    fn=self.get_history,
                    outputs=[history_table],
                )

            with gr.Tab("分类预览"):
                with gr.Row():
                    session_input = gr.Textbox(label="Session ID", placeholder="输入要查看的 session ID")
                    load_btn = gr.Button("加载")
                with gr.Row():
                    category_display = gr.Textbox(label="当前分类")
                    category_edit = gr.Textbox(label="修改分类")
                    confirm_cat_btn = gr.Button("确认分类")

                confirm_cat_btn.click(
                    fn=self.confirm_category,
                    inputs=[session_input, category_edit],
                    outputs=[category_display],
                )

            with gr.Tab("命名预览"):
                with gr.Row():
                    session_input2 = gr.Textbox(label="Session ID", placeholder="输入要查看的 session ID")
                    load_btn2 = gr.Button("加载")
                with gr.Row():
                    original_name = gr.Textbox(label="原始文件名")
                    suggested_name = gr.Textbox(label="建议名称")
                    name_edit = gr.Textbox(label="修改名称")
                    confirm_name_btn = gr.Button("确认命名")

                confirm_name_btn.click(
                    fn=self.confirm_name,
                    inputs=[session_input2, name_edit],
                    outputs=[suggested_name],
                )

            with gr.Tab("日程预览"):
                with gr.Row():
                    session_input3 = gr.Textbox(label="Session ID", placeholder="输入要查看的 session ID")
                    load_btn3 = gr.Button("加载日程")
                with gr.Row():
                    timeline_output = gr.Markdown(label="时间轴")
                    ics_output = gr.Textbox(label="ICS 内容", lines=10)

                load_btn3.click(
                    fn=self.get_milestones_view,
                    inputs=[session_input3],
                    outputs=[timeline_output, ics_output],
                )

            with gr.Tab("文件出题"):
                with gr.Row():
                    with gr.Column(scale=1):
                        study_file_input = gr.File(
                            label="上传学习资料",
                            file_count="single",
                            file_types=[".pdf", ".docx", ".pptx", ".txt", ".md"],
                        )
                        study_upload_btn = gr.Button("上传并解析", variant="primary")
                        study_doc_id = gr.Textbox(label="文档 ID", interactive=False)
                        study_parse_output = gr.Textbox(label="解析结果", interactive=False)

                    with gr.Column(scale=2):
                        study_analyze_btn = gr.Button("AI 分析")
                        study_menu_output = gr.Markdown(label="题型菜单")

                with gr.Row():
                    study_choice_count = gr.Number(label="选择题数量", value=3, precision=0, minimum=0, maximum=10)
                    study_fill_count = gr.Number(label="填空题数量", value=2, precision=0, minimum=0, maximum=10)
                    study_short_count = gr.Number(label="简答题数量", value=1, precision=0, minimum=0, maximum=10)
                    study_generate_btn = gr.Button("按组合出题", variant="primary")

                study_questions_output = gr.Markdown(label="生成的题目")

                with gr.Row():
                    study_docs_refresh_btn = gr.Button("刷新文档列表")
                    study_docs_table = gr.Dataframe(
                        headers=["ID", "文件名", "类型", "状态", "切片数", "大小", "创建时间"],
                        label="文档列表",
                    )

                with gr.Row():
                    study_doc_delete_id = gr.Textbox(label="删除文档 ID")
                    study_doc_delete_btn = gr.Button("删除文档")
                    study_cleanup_btn = gr.Button("清理过期文档")
                    study_doc_manage_output = gr.Markdown(label="文档管理结果")

                study_upload_btn.click(
                    fn=self.upload_and_parse_study,
                    inputs=[study_file_input],
                    outputs=[study_doc_id, study_parse_output],
                )
                study_analyze_btn.click(
                    fn=self.analyze_study_document,
                    inputs=[study_doc_id],
                    outputs=[study_menu_output],
                )
                study_generate_btn.click(
                    fn=self.generate_study_questions,
                    inputs=[study_doc_id, study_choice_count, study_fill_count, study_short_count],
                    outputs=[study_questions_output],
                )
                study_docs_refresh_btn.click(
                    fn=self.get_study_documents_rows,
                    outputs=[study_docs_table],
                )
                study_doc_delete_btn.click(
                    fn=self.delete_study_document,
                    inputs=[study_doc_delete_id],
                    outputs=[study_doc_manage_output],
                )
                study_cleanup_btn.click(
                    fn=self.cleanup_study_documents,
                    outputs=[study_doc_manage_output],
                )

            with gr.Tab("错题本"):
                with gr.Row():
                    with gr.Column(scale=1):
                        answer_question_id = gr.Textbox(label="题目 ID")
                        answer_text = gr.Textbox(label="我的答案", lines=2)
                        answer_btn = gr.Button("提交答案", variant="primary")
                        more_btn = gr.Button("举一反三")
                        answer_output = gr.Markdown(label="判题结果")

                    with gr.Column(scale=2):
                        questions_refresh_btn = gr.Button("刷新题目列表")
                        questions_table = gr.Dataframe(
                            headers=["ID", "题型", "知识点", "题干"],
                            label="题目列表",
                        )
                        wrong_refresh_btn = gr.Button("刷新错题本")
                        wrong_table = gr.Dataframe(
                            headers=["错题ID", "题目ID", "知识点", "阶段", "下次复习", "状态", "题干"],
                            label="错题本",
                        )
                        due_refresh_btn = gr.Button("今日待复习")
                        due_table = gr.Dataframe(
                            headers=["错题ID", "题目ID", "知识点", "下次复习", "题干"],
                            label="今日待复习",
                        )

                with gr.Row():
                    wrong_item_id = gr.Textbox(label="错题记录 ID")
                    review_btn = gr.Button("复习一次")
                    master_btn = gr.Button("标记掌握")
                    review_output = gr.Markdown(label="复习结果")

                with gr.Row():
                    favorite_btn = gr.Button("收藏/取消收藏")
                    delete_question_btn = gr.Button("删除题目")
                    question_manage_output = gr.Markdown(label="题目管理结果")

                answer_btn.click(
                    fn=self.submit_study_answer,
                    inputs=[answer_question_id, answer_text],
                    outputs=[answer_output],
                )
                more_btn.click(
                    fn=self.generate_more_study_questions,
                    inputs=[answer_question_id],
                    outputs=[answer_output],
                )
                favorite_btn.click(
                    fn=self.favorite_study_question,
                    inputs=[answer_question_id],
                    outputs=[question_manage_output],
                )
                delete_question_btn.click(
                    fn=self.delete_study_question,
                    inputs=[answer_question_id],
                    outputs=[question_manage_output],
                )
                questions_refresh_btn.click(
                    fn=self.get_study_questions_rows,
                    outputs=[questions_table],
                )
                wrong_refresh_btn.click(
                    fn=self.get_wrong_book_rows,
                    outputs=[wrong_table],
                )
                due_refresh_btn.click(
                    fn=self.get_due_reviews_rows,
                    outputs=[due_table],
                )
                review_btn.click(
                    fn=self.review_study_wrong_item,
                    inputs=[wrong_item_id],
                    outputs=[review_output],
                )
                master_btn.click(
                    fn=self.master_study_wrong_item,
                    inputs=[wrong_item_id],
                    outputs=[review_output],
                )

        return app


# =====================================================================
# 便捷函数
# =====================================================================

def create_app() -> gr.Blocks:
    """创建 FileMate 应用。"""
    ui = FileMateUI()
    return ui.build()


def launch_demo() -> None:
    """启动演示应用。"""
    app = create_app()
    app.launch(server_name="0.0.0.0", server_port=7860)


if __name__ == "__main__":
    launch_demo()
