"""Gradio 主界面。"""

from __future__ import annotations

import gradio as gr

from filemate.core.session import ProcessingSession


class FileMateUI:
    """FileMate Gradio 界面。TODO(余恒)"""

    def __init__(self, pipeline_worker, state_store) -> None:
        """初始化 UI。

        Parameters
        ----------
        pipeline_worker : PipelineWorker, optional
            异步处理流水线（可选，推荐使用简化版 API）。
        state_store : SQLiteStorage, optional
            状态存储（可选，推荐使用简化版 API）。
            直接使用 BackendAPI.process_file() 更简洁。
        """
        self.pipeline = pipeline_worker
        self.store = state_store

    def build(self) -> gr.Blocks:
        """TODO(余恒): 构建 4 个 Tab 的 Gradio 界面。

        Tab 结构:
        - 导入：文件上传 + 文件列表
        - 分类预览：建议分类 + 置信度 + 确认/修改
        - 命名预览：原始名 vs 建议名 + 编辑
        - 日程预览：时间轴视图 + 导出 .ics
        """
        raise NotImplementedError("TODO(余恒): Gradio 界面实现")
