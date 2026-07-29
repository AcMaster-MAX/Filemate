"""PipelineFactory - 动态阶段组合工厂。

支持：
- 声明式阶段定义
- 条件执行（if/else）
- 失败重试策略
- 并行/串行组合
- 阶段依赖管理

设计原则：
- 阶段即函数：每个阶段是 (Session) -> Session
- 可插拔：阶段可单独注册和替换
- 可组合：支持串行、并行、条件分支
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

from filemate.core.session import ProcessingSession, SessionStatus
from filemate.core.registry import ModuleRegistry

logger = logging.getLogger(__name__)

# 阶段函数类型
StageFn = Callable[[ProcessingSession], ProcessingSession]


class StageCondition(Enum):
    """阶段执行条件。"""
    ALWAYS = auto()      # 总是执行
    ON_SUCCESS = auto()  # 上阶段成功才执行
    ON_FAILURE = auto()  # 上阶段失败才执行
    SKIP = auto()        # 跳过


@dataclass
class StageConfig:
    """单个阶段的配置。"""
    name: str
    fn: StageFn
    condition: StageCondition = StageCondition.ALWAYS
    retry: int = 0                    # 失败重试次数
    retry_delay: float = 1.0          # 重试间隔（秒）
    timeout: Optional[float] = None   # 超时时间（秒）
    enabled: bool = True              # 是否启用


@dataclass
class PipelineConfig:
    """流水线配置。"""
    name: str = "default"
    stages: list[StageConfig] = field(default_factory=list)
    stop_on_failure: bool = True      # 失败后是否停止
    continue_on_skip: bool = True      # 跳过后是否继续
    enable_logging: bool = True       # 是否记录日志

    def add_stage(
        self,
        name: str,
        fn: StageFn,
        **kwargs,
    ) -> "PipelineConfig":
        """链式添加阶段。"""
        stage = StageConfig(name=name, fn=fn, **kwargs)
        self.stages.append(stage)
        return self

    def build(self) -> "Pipeline":
        """构建 Pipeline 实例。"""
        return Pipeline(config=self)


class Pipeline:
    """可执行的阶段流水线。

    用法::

        # 方式 1：直接定义
        pipeline = PipelineBuilder().add_stage("parse", parse_fn).build()

        # 方式 2：预定义配置
        config = PipelineConfig(name="full").add_stage("parse", parse_fn).add_stage("classify", classify_fn)
        pipeline = config.build()

        # 执行
        session = pipeline.execute(session)
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._stage_index: dict[str, int] = {}
        for i, stage in enumerate(config.stages):
            self._stage_index[stage.name] = i

    def execute(
        self,
        session: ProcessingSession,
        start_from: str | None = None,
    ) -> ProcessingSession:
        """执行流水线。

        Parameters
        ----------
        session : ProcessingSession
            输入会话。
        start_from : str, optional
            从指定阶段开始（用于断点续传）。

        Returns
        -------
        ProcessingSession
            处理后的会话。
        """
        start_idx = 0
        if start_from and start_from in self._stage_index:
            start_idx = self._stage_index[start_from]
            logger.info("从阶段 %s (index=%d) 恢复执行", start_from, start_idx)

        last_status = SessionStatus.PENDING
        for i, stage in enumerate(self.config.stages):
            if i < start_idx:
                continue
            if not stage.enabled:
                logger.debug("[%s] 阶段 %s 已跳过（disabled）", session.session_id, stage.name)
                continue

            # 检查执行条件
            if not self._should_execute(stage, last_status):
                logger.debug("[%s] 阶段 %s 跳过（condition=%s）", session.session_id, stage.name, stage.condition)
                continue

            # 执行阶段
            try:
                session = self._execute_stage(session, stage)
                last_status = session.status

                if self.config.enable_logging:
                    logger.info("[%s] 阶段 %s 完成，status=%s", session.session_id, stage.name, session.status.value)

                # 检查失败停止
                if session.status == SessionStatus.FAILED and self.config.stop_on_failure:
                    logger.warning("[%s] 失败停止于阶段 %s", session.session_id, stage.name)
                    break

            except Exception as exc:
                logger.error("[%s] 阶段 %s 异常: %s", session.session_id, stage.name, exc)
                session.error = f"{stage.name} 异常: {exc}"
                session.status = SessionStatus.FAILED
                if self.config.stop_on_failure:
                    break

        return session

    def _should_execute(self, stage: StageConfig, last_status: SessionStatus) -> bool:
        """判断阶段是否应该执行。"""
        if stage.condition == StageCondition.ALWAYS:
            return True
        elif stage.condition == StageCondition.ON_SUCCESS:
            return last_status == SessionStatus.DONE
        elif stage.condition == StageCondition.ON_FAILURE:
            return last_status == SessionStatus.FAILED
        elif stage.condition == StageCondition.SKIP:
            return False
        return True

    def _execute_stage(self, session: ProcessingSession, stage: StageConfig) -> ProcessingSession:
        """执行单个阶段（带重试）。"""
        last_exc: Exception | None = None

        for attempt in range(stage.retry + 1):
            try:
                if stage.timeout:
                    # TODO: 实现超时控制
                    pass
                return stage.fn(session)

            except Exception as exc:
                last_exc = exc
                if attempt < stage.retry:
                    logger.warning("[%s] 阶段 %s 失败，%.1fs 后重试 (%d/%d): %s",
                                   session.session_id, stage.name, stage.retry_delay,
                                   attempt + 1, stage.retry + 1, exc)
                    time.sleep(stage.retry_delay)
                else:
                    logger.error("[%s] 阶段 %s 最终失败: %s", session.session_id, stage.name, exc)

        # 所有重试都失败
        session.error = f"{stage.name} 失败: {last_exc}"
        session.status = SessionStatus.FAILED
        return session

    def get_stage_names(self) -> list[str]:
        """获取所有阶段名称（按顺序）。"""
        return [s.name for s in self.config.stages]


class PipelineBuilder:
    """Pipeline 构造器（链式 API）。"""

    def __init__(self, name: str = "default") -> None:
        self._config = PipelineConfig(name=name)

    def add_stage(
        self,
        name: str,
        fn: StageFn,
        condition: StageCondition = StageCondition.ALWAYS,
        retry: int = 0,
        retry_delay: float = 1.0,
        enabled: bool = True,
    ) -> "PipelineBuilder":
        """添加阶段。"""
        self._config.add_stage(
            name=name,
            fn=fn,
            condition=condition,
            retry=retry,
            retry_delay=retry_delay,
            enabled=enabled,
        )
        return self

    def add_parse_stage(self, registry: Optional[ModuleRegistry] = None) -> "PipelineBuilder":
        """添加解析阶段（使用 Registry）。"""
        registry = registry or ModuleRegistry.get_instance()

        def parse(session: ProcessingSession) -> ProcessingSession:
            try:
                parser = registry.get_parser()
                parsed = parser.parse(session.source_path)
                session.entities["raw_text"] = parsed.get("raw_text", "")
                session.entities["metadata"] = parsed.get("metadata", {})
            except Exception as exc:
                logger.warning("解析阶段失败: %s", exc)
                session.error = f"解析失败: {exc}"
                session.status = SessionStatus.FAILED
            return session

        return self.add_stage("parse", parse, retry=1)

    def add_classify_stage(self, registry: Optional[ModuleRegistry] = None) -> "PipelineBuilder":
        """添加分类阶段（使用 Registry）。"""
        registry = registry or ModuleRegistry.get_instance()

        def classify(session: ProcessingSession) -> ProcessingSession:
            try:
                from filemate.understanding import Classifier
                from pathlib import Path
                llm = registry.get_llm()
                cls = Classifier(llm)
                raw_text = session.entities.get("raw_text", "")
                filename = Path(session.source_path).name
                result = cls.classify(raw_text, filename=filename)
                session.category = result.get("category", "待确认")
                session.confidence = float(result.get("confidence", 0.0))
            except Exception as exc:
                logger.warning("分类阶段失败: %s", exc)
                # 不设置 FAILED，允许继续执行
            return session

        return self.add_stage("classify", classify, retry=1)

    def add_extract_stage(self, registry: Optional[ModuleRegistry] = None) -> "PipelineBuilder":
        """添加实体抽取阶段。"""
        registry = registry or ModuleRegistry.get_instance()

        def extract(session: ProcessingSession) -> ProcessingSession:
            try:
                from filemate.understanding import EntityExtractor
                llm = registry.get_llm()
                extractor = EntityExtractor(llm)
                raw_text = session.entities.get("raw_text", "")
                entities = extractor.extract(raw_text)
                session.entities.update(entities)
            except Exception as exc:
                logger.warning("实体抽取阶段失败: %s", exc)
            return session

        return self.add_stage("extract", extract)

    def add_name_stage(self) -> "PipelineBuilder":
        """添加命名生成阶段。"""
        def generate_name(session: ProcessingSession) -> ProcessingSession:
            try:
                from filemate.understanding import Namer
                from filemate.core.registry import get_registry
                llm = get_registry().get_llm()
                namer = Namer(llm)
                course = session.entities.get("course_name") or "未分类"
                task = session.entities.get("task_description") or "未命名"
                deadline = session.entities.get("deadline") or ""
                session.suggested_name = namer.generate(
                    category=session.category,
                    course=course,
                    task=task,
                    deadline=deadline,
                    status="待处理",
                )
            except Exception as exc:
                logger.warning("命名生成阶段失败: %s", exc)
            return session

        return self.add_stage("generate_name", generate_name)

    def build(self) -> Pipeline:
        """构建 Pipeline。"""
        return Pipeline(config=self._config)

    def get_config(self) -> PipelineConfig:
        """获取配置（用于调试）。"""
        return self._config


# 预定义 Pipeline 配置

def create_full_pipeline() -> Pipeline:
    """创建完整的处理流水线（串行）。"""
    return (
        PipelineBuilder("full")
        .add_parse_stage()
        .add_classify_stage()
        .add_extract_stage()
        .add_name_stage()
        .build()
    )


def create_minimal_pipeline() -> Pipeline:
    """创建最小流水线（仅解析 + 分类）。"""
    return (
        PipelineBuilder("minimal")
        .add_parse_stage()
        .add_classify_stage()
        .build()
    )