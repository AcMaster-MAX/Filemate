"""Step 3.7 Speed 供应商实现（OpenAI 兼容接口）。"""

from __future__ import annotations

import logging
from typing import Any

import requests

from ..config import LLMConfig
from ..exceptions import (
    LLMAPIError,
    LLMConfigError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .base import BaseLLMProvider

logger = logging.getLogger(__name__)


class StepSpeedProvider(BaseLLMProvider):
    """对接 Step 3.7 Speed 大批量调用渠道。

    配置来源（按优先级）：
    1. 构造函数显式传入的 LLMConfig
    2. 环境变量（.env）
    """

    def __init__(self, config: LLMConfig) -> None:
        if not config.api_key:
            raise LLMConfigError("LLM_API_KEY 未配置，请在 .env 中设置")
        if not config.base_url:
            raise LLMConfigError("LLM_BASE_URL 未配置，请在 .env 中设置")
        if not config.model:
            raise LLMConfigError("LLM_MODEL 未配置，请在 .env 中设置")
        self.config = config

    # ------------------------------------------------------------------
    # BaseLLMProvider 接口
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> str:
        """发起一次 Step API 调用，返回纯文本回复。"""
        # 判断使用哪种API端点
        base_url_lower = self.config.base_url.lower()

        # 云知声 (unisound) 使用 /v1/messages
        if "unisound" in base_url_lower or "anthropic" in base_url_lower:
            url = f"{self.config.base_url.rstrip('/')}/v1/messages"
            payload: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        # Step Plan 使用 /v1/messages
        elif "step_plan" in base_url_lower:
            url = f"{self.config.base_url.rstrip('/')}/messages"
            payload = {
                "model": self.config.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        # 其他使用 Chat Completions API
        else:
            url = f"{self.config.base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": self.config.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format:
                payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        logger.debug("Step API 调用: %s | messages=%d 条", url, len(messages))

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.Timeout as exc:
            raise LLMTimeoutError(f"Step API 调用超时（{timeout}s）") from exc
        except requests.ConnectionError as exc:
            raise LLMAPIError(f"Step API 连接失败: {exc}") from exc

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "5")
            raise LLMRateLimitError(f"触发限流，{retry_after}s 后重试")

        if resp.status_code != 200:
            raise LLMAPIError(
                f"Step API 返回 {resp.status_code}: {resp.text[:500]}"
            )

        body = resp.json()
        try:
            # 根据API类型解析响应
            text = ""
            # 方式1: Messages API 格式 (content 是列表)
            if "content" in body and isinstance(body["content"], list):
                text_parts: list[str] = []
                thinking_parts: list[str] = []
                for item in body["content"]:
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif item.get("type") == "thinking":
                        thinking = item.get("thinking", "")
                        if thinking:
                            thinking_parts.append(thinking)
                text = "".join(text_parts)
                # 若模型只返回了 thinking block（token 耗尽等情况），把 thinking 作为 fallback
                if not text and thinking_parts:
                    text = "\n\n".join(thinking_parts)
            # 方式2: Messages API 格式 (content 是字符串)
            elif "content" in body and isinstance(body["content"], str):
                text = body["content"]
            # 方式3: Chat Completions 格式
            elif "choices" in body:
                msg = body["choices"][0]["message"]
                text = msg.get("content", "")
                # 有些模型把内容放在 reasoning_content
                if not text:
                    text = msg.get("reasoning_content", "")
            # 兜底：搜索常见字段
            if not text:
                for key in ("text", "response", "output", "result"):
                    if key in body and isinstance(body[key], str):
                        text = body[key]
                        break

            if not text:
                logger.warning("LLM 返回空内容，响应结构: %s",
                               {k: type(v).__name__ for k, v in body.items()})
        except (KeyError, IndexError) as exc:
            raise LLMAPIError(f"Step API 响应格式异常: {body}") from exc

        return text
