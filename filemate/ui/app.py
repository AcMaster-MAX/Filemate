"""FileMate Gradio 界面 - 完整实现。

四个 Tab：
1. 导入：文件上传 + 文件列表
2. 分类预览：建议分类 + 置信度 + 确认/修改
3. 命名预览：原始名 vs 建议名 + 编辑
4. 日程预览：时间轴视图 + 导出 .ics
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