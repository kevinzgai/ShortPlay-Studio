"""SQLite 落库：llm_calls 表（LLM 调用台账）。

为什么在 app/config/：和 llm_store / engine_store 同级——都是「本机状态读写」，
不含业务判断。库文件在 data/llm_calls.db（.gitignore 已排除）。

隐私红线（沿用主设计原则）：只存字符数与 token 用量，**不存 prompt/completion
原文、不存 apiKey**。
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from app.paths import ROOT

DB_PATH = ROOT / "data" / "llm_calls.db"

_LOCK = threading.Lock()
_CONN = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  ts               TEXT    NOT NULL,
  call_path        TEXT    NOT NULL,
  provider_id      TEXT    NOT NULL,
  base_url         TEXT    NOT NULL,
  model            TEXT    NOT NULL,
  attempt          INTEGER NOT NULL DEFAULT 1,
  ok               INTEGER NOT NULL,
  latency_ms       INTEGER,
  prompt_chars     INTEGER,
  completion_chars INTEGER,
  finish_reason    TEXT,
  prompt_tokens    INTEGER,
  completion_tokens INTEGER,
  total_tokens     INTEGER,
  error            TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
"""


def _conn():
    """单连接 + WAL。线程安全靠一把锁（本项目 QPS 极低，够用）。"""
    global _CONN
    if _CONN is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _CONN = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _CONN.execute("PRAGMA journal_mode=WAL")
        _CONN.executescript(_SCHEMA)
        _CONN.commit()
    return _CONN


def record_llm_call(*, call_path, provider_id, base_url, model, attempt=1,
                    ok, latency_ms=None, prompt_chars=None, completion_chars=None,
                    finish_reason=None, usage=None, error=None):
    """写一行调用记录。**任何异常只打 stderr，绝不向业务层抛**——
    台账写坏了不能拖垮主流程（技术方案 §7 的回滚底线）。
    usage 兼容 dict（OpenAI 格式 {"prompt_tokens":..,"completion_tokens":..,"total_tokens":..}）。
    """
    try:
        usage = usage or {}
        row = (
            datetime.now().isoformat(timespec="seconds"),
            str(call_path)[:120],
            str(provider_id or "")[:60],
            str(base_url or "")[:300],
            str(model or "")[:120],
            int(attempt or 1),
            1 if ok else 0,
            int(latency_ms) if latency_ms is not None else None,
            int(prompt_chars) if prompt_chars is not None else None,
            int(completion_chars) if completion_chars is not None else None,
            str(finish_reason or "")[:40] or None,
            _int_or_none(usage.get("prompt_tokens")),
            _int_or_none(usage.get("completion_tokens")),
            _int_or_none(usage.get("total_tokens")),
            str(error or "")[:200] or None,
        )
        with _LOCK:
            c = _conn()
            c.execute(
                "INSERT INTO llm_calls (ts, call_path, provider_id, base_url, model,"
                " attempt, ok, latency_ms, prompt_chars, completion_chars,"
                " finish_reason, prompt_tokens, completion_tokens, total_tokens, error)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            c.commit()
    except Exception as exc:  # noqa: BLE001 —— 故意吞掉：台账失败不连坐业务
        import sys
        print("[llm_calls] 台账写入失败（不影响业务）：%r" % exc, file=sys.stderr)


def _int_or_none(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def llm_calls_recent(limit=100):
    """最近 N 条调用（管理页排查用；脱敏：不含原文与 Key，天然安全）。"""
    with _LOCK:
        rows = _conn().execute(
            "SELECT ts, call_path, provider_id, model, attempt, ok, latency_ms,"
            " prompt_chars, completion_chars, finish_reason,"
            " prompt_tokens, completion_tokens, total_tokens, error"
            " FROM llm_calls ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    keys = ["ts", "callPath", "providerId", "model", "attempt", "ok", "latencyMs",
            "promptChars", "completionChars", "finishReason",
            "promptTokens", "completionTokens", "totalTokens", "error"]
    return [dict(zip(keys, r)) for r in rows]


def llm_calls_stats():
    """按 call_path 聚合：调用数 / 成功率 / 平均耗时 / token 总量。"""
    with _LOCK:
        rows = _conn().execute(
            "SELECT call_path, COUNT(*), SUM(ok), AVG(latency_ms),"
            " SUM(prompt_tokens), SUM(completion_tokens)"
            " FROM llm_calls GROUP BY call_path ORDER BY COUNT(*) DESC").fetchall()
    return [{"callPath": r[0], "calls": r[1], "ok": r[2] or 0,
             "avgLatencyMs": round(r[3] or 0), "promptTokens": r[4] or 0,
             "completionTokens": r[5] or 0} for r in rows]
