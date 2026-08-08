"""SQLite 持久化。

Schema 与《项目总纲 v1.0》§3.6 对齐。
"""

from __future__ import annotations

import sqlite3
import json
import threading
import time
import functools
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


# ──────────────────────────────────────────────
#  写操作重试（多线程并发写入时自动重试）
# ──────────────────────────────────────────────

def _retry_on_lock(
    max_attempts: int = 3,
    backoff: float = 0.05,
) -> Callable:
    """装饰器：遇到 database is locked 自动重试。"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except sqlite3.OperationalError as exc:
                    if "locked" in str(exc).lower() and attempt < max_attempts:
                        time.sleep(backoff * attempt)
                        continue
                    raise
        return wrapper
    return decorator


# ──────────────────────────────────────────────
#  Schema（与 项目总纲 §3.6 保持一致）
# ──────────────────────────────────────────────

_SCHEMA = """\
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    source_path      TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK(status IN ('pending','processing','done','confirmed','skipped','expired','failed')),
    category         TEXT,
    confidence       REAL,
    suggested_name   TEXT,
    entities         TEXT,   -- JSON
    milestones       TEXT,   -- JSON
    error            TEXT,
    user_modified    INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS processed_files (
    file_hash         TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL REFERENCES sessions(session_id),
    first_seen_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    last_processed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    process_count     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS operation_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT NOT NULL REFERENCES sessions(session_id),
    action            TEXT NOT NULL,
    detail            TEXT DEFAULT '',
    input_snapshot    TEXT,
    user_override     TEXT,
    latency_ms        INTEGER,
    model_used        TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS user_rules (
    rule_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type   TEXT NOT NULL,
    pattern     TEXT NOT NULL,
    replacement TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_status    ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_created   ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_operation_log_sid  ON operation_log(session_id);
CREATE INDEX IF NOT EXISTS idx_operation_log_ts   ON operation_log(created_at);

-- 文件出题与错题本
CREATE TABLE IF NOT EXISTS documents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT NOT NULL DEFAULT 'local',
    filename         TEXT NOT NULL,
    file_type        TEXT NOT NULL,
    storage_path     TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'uploaded',
    chunks_count     INTEGER NOT NULL DEFAULT 0,
    size_bytes       INTEGER NOT NULL DEFAULT 0,
    temp_cleanup_at  TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    content       TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS file_analyze_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    menu_json   TEXT NOT NULL,
    message     TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL DEFAULT 'local',
    document_id     INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    subject         TEXT DEFAULT '',
    knowledge_point TEXT DEFAULT '',
    question_type   TEXT NOT NULL,
    stem            TEXT NOT NULL,
    options_json    TEXT DEFAULT '[]',
    answer          TEXT DEFAULT '',
    analysis        TEXT DEFAULT '',
    source          TEXT DEFAULT 'ai',
    is_favorite     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS answer_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL DEFAULT 'local',
    question_id   INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    user_answer   TEXT DEFAULT '',
    is_correct    INTEGER NOT NULL DEFAULT 0,
    spent_seconds INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS wrong_book_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT NOT NULL DEFAULT 'local',
    question_id      INTEGER NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
    mistake_reason   TEXT DEFAULT '',
    review_count     INTEGER NOT NULL DEFAULT 0,
    mastered         INTEGER NOT NULL DEFAULT 0,
    review_stage     INTEGER NOT NULL DEFAULT 1,
    next_review_date TEXT NOT NULL,
    last_reviewed_at TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_user       ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc  ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_questions_user        ON questions(user_id);
CREATE INDEX IF NOT EXISTS idx_answer_records_user   ON answer_records(user_id);
CREATE INDEX IF NOT EXISTS idx_wrong_book_user       ON wrong_book_items(user_id);
CREATE INDEX IF NOT EXISTS idx_wrong_book_due        ON wrong_book_items(user_id, mastered, next_review_date);
"""


# update_session / update_rule 允许更新的列（防止拼写错误；SQL 注入已由参数化查询防御）
_ALLOWED_SESSION_COLS = {
    "status", "category", "confidence", "suggested_name",
    "entities", "milestones", "error", "user_modified",
}
_ALLOWED_RULE_COLS = {"pattern", "replacement", "priority", "enabled"}
_ALLOWED_STUDY_DOC_COLS = {"status", "chunks_count", "filename", "temp_cleanup_at"}
_ALLOWED_WRONG_BOOK_COLS = {
    "mistake_reason",
    "review_count",
    "mastered",
    "review_stage",
    "next_review_date",
    "last_reviewed_at",
}


class SQLiteStorage:
    """SQLite 存储封装（四张表 + 线程安全）。

    每张表提供最小完备的 CRUD 接口，调用方通过方法字段参数与表列交互。
    """

    def __init__(self, db_path: str | Path = "filemate.db") -> None:
        self.db_path = Path(db_path)
        self._local = threading.local()

    # ------------------------------------------------------------------
    # 内部：每个线程持有一条连接
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
                timeout=30,  # 等待写锁释放（秒），不立刻报 SQLITE_BUSY
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """建表 + 约束 + 索引。幂等，可重复调用。"""
        conn = self._conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    # ------------------------------------------------------------------
    # sessions 表
    # ------------------------------------------------------------------

    @_retry_on_lock()
    def create_session(self, session_id: str, source_path: str) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, source_path) VALUES (?, ?)",
            (session_id, str(source_path)),
        )
        conn.commit()

    @_retry_on_lock()
    def update_session(self, session_id: str, **kwargs: Any) -> None:
        """按字段名更新 session。自动刷新 updated_at。

        支持的字段：status, category, confidence, suggested_name,
        entities, milestones, error, user_modified。
        """
        if not kwargs:
            return
        invalid = set(kwargs) - _ALLOWED_SESSION_COLS
        if invalid:
            raise ValueError(
                f"无效字段: {sorted(invalid)}，允许: {sorted(_ALLOWED_SESSION_COLS)}"
            )
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [datetime.now().isoformat(timespec="seconds"), session_id]
        conn = self._conn()
        conn.execute(
            f"UPDATE sessions SET {set_clause}, updated_at=? WHERE session_id=?",
            values,
        )
        conn.commit()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(
        self, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        conn = self._conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        """删除 session 及其关联的操作日志与去重记录。返回是否实际删除了行。"""
        conn = self._conn()
        conn.execute("DELETE FROM operation_log WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM processed_files WHERE session_id=?", (session_id,))
        cur = conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # processed_files 表
    # ------------------------------------------------------------------

    def is_duplicate(self, file_hash: str) -> bool:
        conn = self._conn()
        row = conn.execute(
            "SELECT 1 FROM processed_files WHERE file_hash=?", (file_hash,)
        ).fetchone()
        return row is not None

    @_retry_on_lock()
    def record_hash(self, file_hash: str, session_id: str) -> None:
        """记录文件哈希（新建或更新处理时间+计数）。

        调用方应在调用本方法前先通过 create_session() 创建 session。
        若 session 尚不存在，自动创建占位记录以保证 FK 不报错
        （source_path 为 __auto_created__ 前缀，方便排查调用顺序问题）。
        """
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, source_path) VALUES (?, ?)",
            (session_id, f"__auto_created__/{session_id}"),
        )
        conn.execute(
            """INSERT INTO processed_files (file_hash, session_id)
               VALUES (?, ?)
               ON CONFLICT(file_hash) DO UPDATE SET
                   last_processed_at = strftime('%Y-%m-%dT%H:%M:%S','now'),
                   process_count = process_count + 1""",
            (file_hash, session_id),
        )
        conn.commit()

    def get_file_info(self, file_hash: str) -> dict[str, Any] | None:
        """查询某个哈希的历史处理信息。"""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM processed_files WHERE file_hash=?", (file_hash,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # operation_log 表
    # ------------------------------------------------------------------

    @_retry_on_lock()
    def log_operation(
        self,
        session_id: str,
        action: str,
        detail: str = "",
        *,
        input_snapshot: str | None = None,
        user_override: str | None = None,
        latency_ms: int | None = None,
        model_used: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> int:
        """写入操作日志。返回自增 id。

        新增的 keyword-only 字段对齐项目总纲 §3.6，用于 Prompt 迭代分析。
        """
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO operation_log
               (session_id, action, detail, input_snapshot, user_override,
                latency_ms, model_used, prompt_tokens, completion_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, action, detail, input_snapshot, user_override,
                latency_ms, model_used, prompt_tokens, completion_tokens,
            ),
        )
        conn.commit()
        return cur.lastrowid

    def get_operations(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM operation_log WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # user_rules 表
    # ------------------------------------------------------------------

    @_retry_on_lock()
    def add_rule(
        self,
        rule_type: str,
        pattern: str,
        replacement: str,
        priority: int = 0,
    ) -> int:
        """添加用户自定义规则。返回 rule_id。"""
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO user_rules (rule_type, pattern, replacement, priority)
               VALUES (?, ?, ?, ?)""",
            (rule_type, pattern, replacement, priority),
        )
        conn.commit()
        return cur.lastrowid

    def update_rule(self, rule_id: int, **kwargs: Any) -> bool:
        """更新规则字段（pattern, replacement, priority, enabled 等）。"""
        if not kwargs:
            return False
        invalid = set(kwargs) - _ALLOWED_RULE_COLS
        if invalid:
            raise ValueError(
                f"无效字段: {sorted(invalid)}，允许: {sorted(_ALLOWED_RULE_COLS)}"
            )
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [rule_id]
        conn = self._conn()
        cur = conn.execute(
            f"UPDATE user_rules SET {set_clause} WHERE rule_id=?",
            values,
        )
        conn.commit()
        return cur.rowcount > 0

    def delete_rule(self, rule_id: int) -> bool:
        """删除规则。返回是否实际删除了行。"""
        conn = self._conn()
        cur = conn.execute("DELETE FROM user_rules WHERE rule_id=?", (rule_id,))
        conn.commit()
        return cur.rowcount > 0

    def list_rules(
        self, rule_type: str | None = None, enabled_only: bool = True
    ) -> list[dict[str, Any]]:
        conn = self._conn()
        clauses = []
        params: list[Any] = []
        if enabled_only:
            clauses.append("enabled=1")
        if rule_type:
            clauses.append("rule_type=?")
            params.append(rule_type)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM user_rules{where} ORDER BY priority DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 文件出题：documents / knowledge_chunks / file_analyze_results
    # ------------------------------------------------------------------

    @_retry_on_lock()
    def create_study_document(
        self,
        *,
        user_id: str,
        filename: str,
        file_type: str,
        storage_path: str,
        size_bytes: int,
        temp_cleanup_at: str | None = None,
    ) -> int:
        """新增上传文档，返回 document id。"""
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO documents
               (user_id, filename, file_type, storage_path, size_bytes, temp_cleanup_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, filename, file_type, storage_path, size_bytes, temp_cleanup_at),
        )
        conn.commit()
        return int(cur.lastrowid)

    def list_study_documents(self, user_id: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM documents WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_study_document(
        self, document_id: int, user_id: str
    ) -> dict[str, Any] | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM documents WHERE id=? AND user_id=?",
            (document_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    @_retry_on_lock()
    def update_study_document(self, document_id: int, **kwargs: Any) -> bool:
        if not kwargs:
            return False
        invalid = set(kwargs) - _ALLOWED_STUDY_DOC_COLS
        if invalid:
            raise ValueError(
                f"无效字段: {sorted(invalid)}，允许: {sorted(_ALLOWED_STUDY_DOC_COLS)}"
            )
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [document_id]
        conn = self._conn()
        cur = conn.execute(
            f"UPDATE documents SET {set_clause} WHERE id=?", values
        )
        conn.commit()
        return cur.rowcount > 0

    @_retry_on_lock()
    def delete_study_document(self, document_id: int, user_id: str) -> bool:
        """删除文档及其切片/分析结果，题目保留但解除文档关联。"""
        conn = self._conn()
        conn.execute(
            "UPDATE questions SET document_id=NULL WHERE document_id=?",
            (document_id,),
        )
        conn.execute(
            "DELETE FROM file_analyze_results WHERE document_id=?", (document_id,)
        )
        conn.execute(
            "DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,)
        )
        cur = conn.execute(
            "DELETE FROM documents WHERE id=? AND user_id=?", (document_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0

    def list_expired_documents(
        self, user_id: str, today: str
    ) -> list[dict[str, Any]]:
        """查询临时文件已过期的文档。"""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM documents WHERE user_id=? AND temp_cleanup_at IS NOT NULL AND temp_cleanup_at <= ?",
            (user_id, today),
        ).fetchall()
        return [dict(r) for r in rows]

    @_retry_on_lock()
    def add_knowledge_chunks(self, document_id: int, chunks: list[str]) -> int:
        conn = self._conn()
        rows = [
            (document_id, index, content)
            for index, content in enumerate(chunks)
        ]
        conn.executemany(
            "INSERT INTO knowledge_chunks (document_id, chunk_index, content) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)

    def get_knowledge_chunks(
        self,
        document_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conn = self._conn()
        if limit is None:
            rows = conn.execute(
                "SELECT * FROM knowledge_chunks WHERE document_id=? ORDER BY chunk_index",
                (document_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_chunks WHERE document_id=? ORDER BY chunk_index LIMIT ? OFFSET ?",
                (document_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    @_retry_on_lock()
    def delete_knowledge_chunks(self, document_id: int) -> int:
        conn = self._conn()
        cur = conn.execute(
            "DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,)
        )
        conn.commit()
        return cur.rowcount

    @_retry_on_lock()
    def save_file_analyze_result(
        self, document_id: int, menu_json: str, message: str
    ) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO file_analyze_results (document_id, menu_json, message)
               VALUES (?, ?, ?)
               ON CONFLICT(document_id) DO UPDATE SET
                   menu_json=excluded.menu_json,
                   message=excluded.message,
                   created_at=strftime('%Y-%m-%dT%H:%M:%S','now')""",
            (document_id, menu_json, message),
        )
        conn.commit()

    def get_file_analyze_result(
        self, document_id: int
    ) -> dict[str, Any] | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM file_analyze_results WHERE document_id=?",
            (document_id,),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # 出题：questions
    # ------------------------------------------------------------------

    @_retry_on_lock()
    def save_questions(self, rows: list[dict[str, Any]]) -> list[int]:
        """批量保存题目，返回 question id 列表。"""
        ids: list[int] = []
        conn = self._conn()
        for row in rows:
            cur = conn.execute(
                """INSERT INTO questions
                   (user_id, document_id, subject, knowledge_point, question_type,
                    stem, options_json, answer, analysis, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row.get("user_id", "local"),
                    row.get("document_id"),
                    row.get("subject", ""),
                    row.get("knowledge_point", ""),
                    row.get("question_type", "choice"),
                    row.get("stem", ""),
                    row.get("options_json", "[]"),
                    row.get("answer", ""),
                    row.get("analysis", ""),
                    row.get("source", "ai"),
                ),
            )
            ids.append(int(cur.lastrowid))
        conn.commit()
        return ids

    def list_questions(
        self, user_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM questions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._question_to_dict(r) for r in rows]

    def get_question(
        self, question_id: int, user_id: str
    ) -> dict[str, Any] | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM questions WHERE id=? AND user_id=?",
            (question_id, user_id),
        ).fetchone()
        return self._question_to_dict(row) if row else None

    @staticmethod
    def _question_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["options"] = json.loads(data.get("options_json") or "[]")
        except json.JSONDecodeError:
            data["options"] = []
        return data

    @_retry_on_lock()
    def set_question_favorite(
        self, question_id: int, user_id: str, is_favorite: int
    ) -> bool:
        conn = self._conn()
        cur = conn.execute(
            "UPDATE questions SET is_favorite=? WHERE id=? AND user_id=?",
            (is_favorite, question_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0

    @_retry_on_lock()
    def delete_question(self, question_id: int, user_id: str) -> bool:
        conn = self._conn()
        conn.execute("DELETE FROM answer_records WHERE question_id=?", (question_id,))
        conn.execute("DELETE FROM wrong_book_items WHERE question_id=?", (question_id,))
        cur = conn.execute(
            "DELETE FROM questions WHERE id=? AND user_id=?", (question_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # 作答与错题本
    # ------------------------------------------------------------------

    @_retry_on_lock()
    def add_answer_record(
        self,
        user_id: str,
        question_id: int,
        user_answer: str,
        is_correct: int,
        spent_seconds: int = 0,
    ) -> int:
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO answer_records
               (user_id, question_id, user_answer, is_correct, spent_seconds)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, question_id, user_answer, is_correct, spent_seconds),
        )
        conn.commit()
        return int(cur.lastrowid)

    @_retry_on_lock()
    def add_wrong_book_item(
        self,
        *,
        user_id: str,
        question_id: int,
        mistake_reason: str,
        next_review_date: str,
    ) -> int:
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO wrong_book_items
               (user_id, question_id, mistake_reason, next_review_date)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(question_id) DO UPDATE SET
                   mistake_reason=excluded.mistake_reason,
                   next_review_date=excluded.next_review_date""",
            (user_id, question_id, mistake_reason, next_review_date),
        )
        conn.commit()
        return int(cur.lastrowid)

    def get_wrong_book_item(
        self, user_id: str, question_id: int
    ) -> dict[str, Any] | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM wrong_book_items WHERE user_id=? AND question_id=?",
            (user_id, question_id),
        ).fetchone()
        return dict(row) if row else None

    def get_wrong_book_item_by_id(
        self, item_id: int, user_id: str
    ) -> dict[str, Any] | None:
        conn = self._conn()
        row = conn.execute(
            """SELECT w.*, q.subject AS subject, q.knowledge_point AS knowledge_point,
                      q.question_type AS question_type, q.stem AS question_stem,
                      q.answer AS correct_answer, q.analysis AS analysis
               FROM wrong_book_items w
               JOIN questions q ON q.id = w.question_id
               WHERE w.id=? AND w.user_id=?""",
            (item_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    @_retry_on_lock()
    def update_wrong_book_item(self, item_id: int, **kwargs: Any) -> bool:
        if not kwargs:
            return False
        invalid = set(kwargs) - _ALLOWED_WRONG_BOOK_COLS
        if invalid:
            raise ValueError(
                f"无效字段: {sorted(invalid)}，允许: {sorted(_ALLOWED_WRONG_BOOK_COLS)}"
            )
        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [item_id]
        conn = self._conn()
        cur = conn.execute(
            f"UPDATE wrong_book_items SET {set_clause} WHERE id=?", values
        )
        conn.commit()
        return cur.rowcount > 0

    def list_wrong_book(self, user_id: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT w.*, q.subject AS subject, q.knowledge_point AS knowledge_point,
                      q.question_type AS question_type, q.stem AS question_stem,
                      q.answer AS correct_answer, q.analysis AS analysis
               FROM wrong_book_items w
               JOIN questions q ON q.id = w.question_id
               WHERE w.user_id=?
               ORDER BY w.created_at DESC""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_due_wrong_book(
        self, user_id: str, today: str
    ) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT w.*, q.subject AS subject, q.knowledge_point AS knowledge_point,
                      q.question_type AS question_type, q.stem AS question_stem,
                      q.answer AS correct_answer, q.analysis AS analysis
               FROM wrong_book_items w
               JOIN questions q ON q.id = w.question_id
               WHERE w.user_id=? AND w.mastered=0 AND w.next_review_date <= ?
               ORDER BY w.next_review_date ASC""",
            (user_id, today),
        ).fetchall()
        return [dict(r) for r in rows]
