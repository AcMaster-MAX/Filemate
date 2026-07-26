"""核心编排：Session + PipelineWorker + 全局类别定义。"""
from .categories import CATEGORIES
from .session import ProcessingSession
from .pipeline import PipelineWorker
__all__ = ["CATEGORIES", "ProcessingSession", "PipelineWorker"]
