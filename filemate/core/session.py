"""ProcessingSession：单个文件从入队到完成的完整状态记录。

状态机设计：
- pending → processing → (paused) → done → confirmed/skipped/expired/failed
- paused → processing（恢复）
- waiting_confirmation → confirmed/skipped（用户确认）

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class SessionStatus(str, Enum):
    """Session 状态机。

    完整状态流转图：
    ┌─────────┐    ┌───────────┐    ┌──────────┐    ┌─────────────┐
    │ pending │───▶│ processing│───▶│   done   │───▶│ confirmed   │
    └─────────┘    └───────────┘    └──────────┘    └─────────────┘
                                  └──────────┐
                                             ├─────────▶ skipped
                                             ├─────────▶ expired
                                             └─────────▶ failed
    ┌───────────┐         ┌──────────────┐
    │  paused   │◀───────│ waiting_confirm
    └───────────┘         └──────────────┘
    """

    PENDING = "pending"                   # 等待处理
    PROCESSING = "processing"               # 处理中
    PAUSED = "paused"                      # 暂停（等待用户交互）
    DONE = "done"                          # 处理完成，待确认
    WAITING_CONFIRMATION = "waiting_confirmation"  # 等待用户确认
    CONFIRMED = "confirmed"                # 用户已确认
    SKIPPED = "skipped"                    # 用户跳过
    EXPIRED = "expired"                    # 已过期
    FAILED = "failed"                      # 处理失败


# 合法状态转移
_VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    # 初始 → 处理中 / 暂停（用户可提前暂停）
    SessionStatus.PENDING: {
        SessionStatus.PROCESSING,
        SessionStatus.PAUSED,  # 用户提前暂停
        SessionStatus.SKIPPED,  # 用户直接跳过
    },
    # 处理中 → 完成/暂停/失败
    SessionStatus.PROCESSING: {
        SessionStatus.DONE,
        SessionStatus.PAUSED,
        SessionStatus.FAILED,
    },
    # 暂停 → 恢复处理
    SessionStatus.PAUSED: {
        SessionStatus.PROCESSING,
        SessionStatus.SKIPPED,
    },
    # 完成 → 待确认/跳过/失败
    SessionStatus.DONE: {
        SessionStatus.WAITING_CONFIRMATION,
        SessionStatus.CONFIRMED,
        SessionStatus.SKIPPED,
        SessionStatus.EXPIRED,
    },
    # 等待确认 → 确认/跳过
    SessionStatus.WAITING_CONFIRMATION: {
        SessionStatus.CONFIRMED,
        SessionStatus.SKIPPED,
    },
    # 确认/跳过/过期 → 终态
    SessionStatus.CONFIRMED: set(),
    SessionStatus.SKIPPED: set(),
    SessionStatus.EXPIRED: set(),
    # 失败 → 重试
    SessionStatus.FAILED: {
        SessionStatus.PROCESSING,
        SessionStatus.PENDING,
    },
}


@dataclass
class ProcessingSession:
    """一个文件 = 一个 session，贯穿全生命周期。

    字段说明：
    - session_id: 唯一标识
    - source_path: 原始文件路径
    - status: 当前状态
    - category: 分类结果
    - confidence: 置信度
    - suggested_name: 建议的文件名
    - entities: 提取的实体（dict）
    - milestones: 识别的时间节点
    - error: 错误信息
    - created_at: 创建时间
    - updated_at: 更新时间

    扩展字段：
    - current_stage: 当前执行的阶段（用于断点续传）
    - pause_reason: 暂停原因
    - metadata: 额外元数据（如来源、标签等）
    """

    session_id: str
    source_path: str = ""
    status: SessionStatus = SessionStatus.PENDING
    category: str = ""
    confidence: float = 0.0
    suggested_name: str = ""
    entities: dict = field(default_factory=dict)
    milestones: list[dict] = field(default_factory=list)
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # 扩展字段
    current_stage: Optional[str] = None  # 当前阶段名称
    pause_reason: Optional[str] = None   # 暂停原因
    metadata: dict = field(default_factory=dict)  # 额外元数据

    # ------------------------------------------------------------------
    # 状态机
    # ------------------------------------------------------------------

    def transition(self, new_status: SessionStatus) -> None:
        """按状态机规则跳转。非法跳转抛 ValueError。"""
        allowed = _VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"状态转换非法: {self.status.value} -> {new_status.value}，"
                f"允许的下一步: {sorted(v.value for v in allowed)}"
            )
        self.status = new_status
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def is_terminal(self) -> bool:
        """是否已进入终态（不能再转移）。"""
        return self.status in {
            SessionStatus.CONFIRMED,
            SessionStatus.SKIPPED,
            SessionStatus.EXPIRED,
        }

    # ------------------------------------------------------------------
    # 状态机 - 扩展方法
    # ------------------------------------------------------------------

    def pause(self, reason: str = "user_action") -> None:
        """暂停处理。"""
        self.transition(SessionStatus.PAUSED)
        self.pause_reason = reason
        self.current_stage = None

    def resume(self) -> None:
        """恢复处理。"""
        self.transition(SessionStatus.PROCESSING)

    def wait_confirmation(self) -> None:
        """进入等待确认状态。"""
        self.transition(SessionStatus.WAITING_CONFIRMATION)

    def confirm(self) -> None:
        """确认（用户接受建议）。"""
        self.transition(SessionStatus.CONFIRMED)

    def skip(self) -> None:
        """跳过（用户拒绝或忽略）。"""
        self.transition(SessionStatus.SKIPPED)

    def expire(self) -> None:
        """标记为过期。"""
        self.transition(SessionStatus.EXPIRED)

    def is_waiting(self) -> bool:
        """是否正在等待用户操作。"""
        return self.status in {
            SessionStatus.PAUSED,
            SessionStatus.WAITING_CONFIRMATION,
            SessionStatus.DONE,
        }

    def can_retry(self) -> bool:
        """是否可以重试。"""
        return self.status == SessionStatus.FAILED

    def get_progress(self) -> dict[str, Any]:
        """获取进度信息。"""
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "current_stage": self.current_stage,
            "has_error": bool(self.error),
            "is_terminal": self.is_terminal(),
            "is_waiting": self.is_waiting(),
        }

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "source_path": self.source_path,
            "status": self.status.value,
            "category": self.category,
            "confidence": self.confidence,
            "suggested_name": self.suggested_name,
            "entities": self.entities,
            "milestones": self.milestones,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            # 扩展字段
            "current_stage": self.current_stage,
            "pause_reason": self.pause_reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProcessingSession":
        raw_status = d.get("status", "pending")
        try:
            status = SessionStatus(raw_status)
        except ValueError:
            status = SessionStatus.PENDING
        return cls(
            session_id=d["session_id"],
            source_path=d.get("source_path", ""),
            status=status,
            category=d.get("category", ""),
            confidence=d.get("confidence", 0.0),
            suggested_name=d.get("suggested_name", ""),
            entities=d.get("entities") or {},
            milestones=d.get("milestones") or [],
            error=d.get("error", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            # 扩展字段
            current_stage=d.get("current_stage"),
            pause_reason=d.get("pause_reason"),
            metadata=d.get("metadata") or {},
        )