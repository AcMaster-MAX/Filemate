"""AI 辅助学习：语义检索 + 对话逻辑 + 总结生成。

设计原则：
- 不用外部向量库，BM25 粗召回 + LLM 查询扩展实现轻量语义检索
- 用户自带 API Key，不走项目默认配置
- 产物（总结文档）写入现有 artifacts 表，artifact_type = 'ai_summary'
"""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from filemate.execution.storage import SQLiteStorage
from filemate.llm_client import LLMClient, LLMConfig

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 轻量 BM25 检索（自包含，不依赖 retrieval.py）
# ──────────────────────────────────────────────

_LATIN = re.compile(r"[a-zA-Z0-9_]+")
_HAN = re.compile(r"[一-鿿]+")


def _tokenize(text: str) -> list[str]:
    """中英文混合分词：英文词 + 中文单字/双字。"""
    lowered = text.lower()
    tokens = _LATIN.findall(lowered)
    for run in _HAN.findall(lowered):
        tokens.append(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """计算 BM25 得分。"""
    if not query_tokens or not doc_tokens:
        return 0.0
    doc_len = len(doc_tokens)
    avg_len = max(1.0, doc_len)  # 简化：单文档时即自身长度
    tf = Counter(doc_tokens)
    score = 0.0
    for qt in set(query_tokens):
        if qt not in tf:
            continue
        f = tf[qt]
        idf = math.log((1 + avg_len) / (1 + f)) + 1
        denom = f + k1 * (1 - b + b * doc_len / avg_len)
        score += idf * f * (k1 + 1) / max(1, denom)
    return score


def bm25_rank(
    query: str,
    chunks: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """对知识库 chunks 做 BM25 粗召回。"""
    qtokens = _tokenize(query)
    if not qtokens or not chunks:
        return []
    scored = []
    for chunk in chunks:
        dtokens = _tokenize(str(chunk.get("content", "")))
        s = _bm25_score(qtokens, dtokens)
        scored.append((s, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:limit]]


# ──────────────────────────────────────────────
# LLM 查询扩展
# ──────────────────────────────────────────────

_QUERY_EXPANSION_PROMPT = """\
你是一个检索助手。用户有一个学习问题，请生成 3 个不同的检索查询，
帮助从知识库中找到最相关的资料片段。

规则：
1. 每个查询 5-15 字
2. 覆盖不同角度：核心概念、相关术语、同义表达
3. 只输出 JSON 数组，不要其他内容

用户问题：{query}
"""


def expand_query(
    query: str,
    llm_client: LLMClient,
) -> list[str]:
    """用 LLM 扩展查询，生成多个检索角度。"""
    prompt = _QUERY_EXPANSION_PROMPT.format(query=query)
    try:
        raw = llm_client.call(
            prompt=prompt,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.3,
        )
        # 提取 JSON
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            queries = json.loads(match.group())
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                return queries[:5]
    except Exception:
        pass
    return [query]  # fallback: 用原查询


# ──────────────────────────────────────────────
# 语义重排
# ──────────────────────────────────────────────

_RERANK_PROMPT = """\
你是一个检索结果排序助手。给定用户问题和若干候选资料片段，
请只返回与问题最相关的片段的序号（从1开始），按相关性从高到低排序。
最多返回 {top_k} 个序号，用逗号分隔，不要其他内容。

用户问题：{query}

候选片段：
{chunks}
"""


def rerank_chunks(
    query: str,
    chunks: list[dict[str, Any]],
    llm_client: LLMClient,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """用 LLM 对 BM25 粗召回结果做语义重排。"""
    if len(chunks) <= top_k:
        return chunks
    chunk_texts = "\n\n".join(
        f"[{i+1}] {c.get('content', '')[:300]}"
        for i, c in enumerate(chunks)
    )
    prompt = _RERANK_PROMPT.format(
        query=query, chunks=chunk_texts, top_k=top_k
    )
    try:
        raw = llm_client.call(
            prompt=prompt,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0.0,
        )
        indices = re.findall(r"\d+", raw)
        ranked = []
        for idx_str in indices[:top_k]:
            idx = int(idx_str) - 1
            if 0 <= idx < len(chunks):
                ranked.append(chunks[idx])
        if ranked:
            return ranked
    except Exception:
        pass
    return chunks[:top_k]


# ──────────────────────────────────────────────
# 学习检索器
# ──────────────────────────────────────────────

class LearningRetriever:
    """AI 学习的知识库检索器：BM25 粗召回 + LLM 扩展 + 语义重排。"""

    def __init__(
        self,
        storage: SQLiteStorage,
        llm_client: LLMClient,
    ) -> None:
        self._storage = storage
        self._llm = llm_client

    def search(
        self,
        query: str,
        *,
        workspace_id: str = "local",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """检索知识库，返回带引用的 chunk 列表。"""
        # 1. 获取所有资料源和 chunks
        sources = self._storage.list_sources(workspace_id=workspace_id, limit=200)
        all_chunks: list[dict[str, Any]] = []
        source_map: dict[str, dict[str, Any]] = {}
        for src in sources:
            sid = src["source_id"]
            source_map[sid] = src
            chunks = self._storage.list_source_chunks(sid)
            for ch in chunks:
                ch["source_id"] = sid
            all_chunks.extend(chunks)

        if not all_chunks:
            return []

        # 2. 查询扩展
        expanded = expand_query(query, self._llm)

        # 3. BM25 粗召回（多查询取并集，然后去重）
        seen: set[int] = set()
        merged: list[dict[str, Any]] = []
        for q in expanded:
            results = bm25_rank(q, all_chunks, limit=limit * 2)
            for r in results:
                idx = id(r)
                if idx not in seen:
                    seen.add(idx)
                    merged.append(r)
            if len(merged) >= limit * 3:
                break

        if not merged:
            return []

        # 4. 语义重排
        final = rerank_chunks(query, merged, self._llm, top_k=limit)

        # 5. 补充来源名称
        for chunk in final:
            src = source_map.get(chunk.get("source_id", ""), {})
            chunk["source_name"] = src.get("original_name", "未知资料")
            chunk["excerpt"] = str(chunk.get("content", ""))[:300]

        return final


# ──────────────────────────────────────────────
# 对话系统提示词
# ──────────────────────────────────────────────

_EXPLORE_SYSTEM = """\
你是 AI 学习助手，正在帮助用户探索一个全新的知识领域。

你的任务：
1. 先给出该领域的核心概念和学习路线概览
2. 根据用户的具体问题，提供清晰、结构化的讲解
3. 适当使用类比、举例帮助理解
4. 如果内容较多，在回复末尾标注【生成文件】并说明将产出什么文件

风格要求：
- 深入浅出，避免堆砌术语
- 分点列出，层次清晰
- 中文回答
"""

_REINFORCE_SYSTEM = """\
你是 AI 学习助手，正在帮助用户巩固已有的知识。

你可以使用提供的知识库资料片段来回答问题。引用资料时请在句子后标注来源编号，如 [1][2]。

规则：
1. 优先基于提供的知识库资料回答
2. 如果知识库资料不够完整，可以补充说明但明确区分哪些来自资料、哪些是你的补充
3. 如果知识库中找不到相关内容，明确告知用户"知识库中暂无此内容"，不要编造
4. 如果知识库中的内容看起来有误或过时，提醒用户注意

风格要求：
- 简洁准确
- 中文回答
"""

_SUMMARY_PROMPT = """\
请总结以下对话内容，生成一份结构化的学习笔记 Markdown 文档。

要求：
1. 标题：根据内容自拟一个简洁标题
2. 包含：核心知识点、关键概念、重要结论、学习建议
3. 格式：Markdown，使用标题层级、列表、加粗等
4. 长度适中，重点突出
5. 直接输出 Markdown 内容，不要额外说明

对话内容：
{conversation}
"""


# ──────────────────────────────────────────────
# AI 学习对话引擎
# ──────────────────────────────────────────────

class AILearningChat:
    """AI 学习对话核心逻辑。"""

    def __init__(
        self,
        storage: SQLiteStorage,
        llm_client: LLMClient,
    ) -> None:
        self._storage = storage
        self._llm = llm_client
        self._retriever = LearningRetriever(storage, llm_client)

    def chat(
        self,
        session_id: str,
        user_message: str,
        mode: str,
        *,
        uploaded_file_text: str = "",
    ) -> dict[str, Any]:
        """发送一条消息并返回 AI 回复。

        返回格式：
        {
            "role": "assistant",
            "content": "AI 回复文本",
            "citations": [...],  # 引用来源
            "message_id": "...",
        }
        """
        # 1. 持久化用户消息
        msg_id = uuid.uuid4().hex[:12]
        citations: list[dict[str, Any]] = []

        # 2. 根据模式构建上下文
        if mode == "reinforce":
            # 检索知识库
            search_results = self._retriever.search(user_message)
            citations = [
                {
                    "source_id": r.get("source_id", ""),
                    "source_name": r.get("source_name", ""),
                    "excerpt": r.get("excerpt", "")[:200],
                    "score": round(_bm25_score(
                        _tokenize(user_message),
                        _tokenize(str(r.get("content", "")))
                    ), 3),
                }
                for r in search_results
            ]
            context_parts = [
                f"[{i+1}] {r.get('source_name', '')}\n{r.get('content', '')[:500]}"
                for i, r in enumerate(search_results)
            ]
            context = "\n\n".join(context_parts) if context_parts else ""
        else:
            context = uploaded_file_text

        # 3. 构建消息列表
        # 注意：step-explore 等模型对 system 消息支持不佳，统一用 user 消息承载指令
        system_prompt = _REINFORCE_SYSTEM if mode == "reinforce" else _EXPLORE_SYSTEM
        messages: list[dict[str, str]] = [
            {"role": "user", "content": f"[系统指令]\n{system_prompt}"}
        ]

        if context:
            if mode == "reinforce":
                messages.append({
                    "role": "user",
                    "content": f"[知识库资料]\n{context}\n\n请基于以上资料回答问题。"
                })
            else:
                messages.append({
                    "role": "user",
                    "content": f"[用户上传的文件内容]\n{context[:8000]}"
                })

        # 加载历史
        history = self._storage.get_ai_messages(session_id)
        for m in history[-10:]:
            messages.append({"role": m["role"], "content": m["content"]})

        messages.append({"role": "user", "content": user_message})

        # 4. 调用 LLM
        try:
            reply = self._llm.call(
                prompt="",
                messages=messages,
                max_tokens=2048,
                temperature=0.7,
            )
        except Exception as exc:
            logger.error("AI 学习对话失败: %s", exc)
            reply = f"抱歉，AI 调用失败：{exc}"

        # 5. 持久化 AI 回复
        self._storage.add_ai_message(
            message_id=uuid.uuid4().hex[:12],
            session_id=session_id,
            role="assistant",
            content=reply,
            citations=citations,
        )

        return {
            "role": "assistant",
            "content": reply,
            "citations": citations,
            "message_id": msg_id,
        }

    def generate_summary(self, session_id: str) -> dict[str, Any]:
        """总结对话内容，生成 Markdown 文档并写入知识库。

        返回格式：
        {
            "artifact_id": "...",
            "title": "...",
            "content": "Markdown 内容",
        }
        """
        # 1. 获取会话信息
        session = self._storage.get_ai_session(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")

        mode = session.get("mode", "explore")
        messages = self._storage.get_ai_messages(session_id)
        if not messages:
            raise ValueError("对话为空，无法总结")

        # 2. 构建对话文本
        conv_parts = []
        for m in messages:
            role_label = "用户" if m["role"] == "user" else "AI"
            conv_parts.append(f"### {role_label}\n{m['content']}")
        conversation = "\n\n".join(conv_parts)

        # 3. 生成总结
        prompt = _SUMMARY_PROMPT.format(conversation=conversation)
        try:
            summary_md = self._llm.call(
                prompt=prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0.5,
            )
        except Exception as exc:
            logger.error("生成总结失败: %s", exc)
            raise RuntimeError(f"生成总结失败: {exc}") from exc

        # 4. 写入 artifacts
        title_prefix = "探索" if mode == "explore" else "巩固"
        title = f"{title_prefix}学习笔记 - {messages[0]['content'][:30]}"
        title = re.sub(r"[^\w\s一-鿿\-]", "", title).strip()
        if not title:
            title = f"{title_prefix}学习笔记"

        source_id = None
        marked_ids = session.get("marked_source_ids", "[]")
        if isinstance(marked_ids, str):
            marked_ids = json.loads(marked_ids)
        if marked_ids:
            source_id = marked_ids[0]

        artifact_id = self._storage.save_artifact(
            source_id=source_id,
            artifact_type="ai_summary",
            title=title,
            content=summary_md,
            metadata={
                "ai_session_id": session_id,
                "mode": mode,
                "message_count": len(messages),
            },
        )

        # 5. 更新会话的 summary_artifact_id
        self._storage.update_ai_session(
            session_id=session_id,
            summary_artifact_id=artifact_id,
        )

        return {
            "artifact_id": artifact_id,
            "title": title,
            "content": summary_md,
        }
