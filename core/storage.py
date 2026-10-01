"""运行历史持久化（SQLite）—— 重启后历史不丢。

- **数据库位置**：`%LOCALAPPDATA%\\ResearchSwarm\\runs.db`
- **设计**：实时状态仍由内存注册表（`app/api.py` 的 `RunRegistry`）负责，SQLite 只在
  **运行结束时归档一次**，因此不会给流水线增加任何负担；查询历史时优先看内存、再回落数据库。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

APP_NAME = "ResearchSwarm"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    query             TEXT NOT NULL,
    status            TEXT NOT NULL,
    stop_reason       TEXT DEFAULT '',
    started_at        TEXT DEFAULT '',
    finished_at       TEXT DEFAULT '',
    duration_ms       INTEGER DEFAULT 0,
    approved          INTEGER DEFAULT 0,
    revision_count    INTEGER DEFAULT 0,
    research_rounds   INTEGER DEFAULT 0,
    report            TEXT DEFAULT '',
    analysis          TEXT DEFAULT '',
    critique          TEXT DEFAULT '',
    plan_json         TEXT DEFAULT '[]',
    failures_json     TEXT DEFAULT '{}',
    sources_json      TEXT DEFAULT '[]',
    usage_json        TEXT DEFAULT '{}',
    error             TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_finished_at ON runs (finished_at DESC);

CREATE TABLE IF NOT EXISTS steps (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    agent        TEXT NOT NULL,
    action       TEXT DEFAULT '',
    at           TEXT DEFAULT '',
    duration_ms  INTEGER,
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps (run_id);
"""


def default_db_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME / "runs.db"


class RunStore:
    """极简归档库：每次操作各自开连接，天然线程安全（写入频率很低）。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ 写
    def save(self, run_id: str, detail: dict[str, Any]) -> None:
        """把一次运行的详情（`RunRecord.detail()` 的形状）归档。"""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, query, status, stop_reason, started_at, finished_at, duration_ms,
                    approved, revision_count, research_rounds, report, analysis, critique,
                    plan_json, failures_json, sources_json, usage_json, error
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status, stop_reason=excluded.stop_reason,
                    finished_at=excluded.finished_at, duration_ms=excluded.duration_ms,
                    approved=excluded.approved, revision_count=excluded.revision_count,
                    research_rounds=excluded.research_rounds, report=excluded.report,
                    analysis=excluded.analysis, critique=excluded.critique,
                    plan_json=excluded.plan_json, failures_json=excluded.failures_json,
                    sources_json=excluded.sources_json, usage_json=excluded.usage_json,
                    error=excluded.error
                """,
                (
                    run_id,
                    detail.get("query", ""),
                    detail.get("status", ""),
                    detail.get("stop_reason", ""),
                    detail.get("started_at", ""),
                    detail.get("finished_at", ""),
                    int(detail.get("duration_ms") or 0),
                    1 if detail.get("approved") else 0,
                    int(detail.get("revision_count") or 0),
                    int(detail.get("research_rounds") or 0),
                    detail.get("report", ""),
                    detail.get("analysis", ""),
                    detail.get("critique", ""),
                    json.dumps(detail.get("plan") or [], ensure_ascii=False),
                    json.dumps(detail.get("failures") or {}, ensure_ascii=False),
                    json.dumps(detail.get("sources") or [], ensure_ascii=False),
                    json.dumps(detail.get("usage") or {}, ensure_ascii=False),
                    detail.get("error", ""),
                ),
            )
            conn.execute("DELETE FROM steps WHERE run_id = ?", (run_id,))
            for entry in detail.get("history") or []:
                conn.execute(
                    "INSERT INTO steps (run_id, agent, action, at, duration_ms) VALUES (?,?,?,?,?)",
                    (
                        run_id,
                        entry.get("agent", ""),
                        entry.get("action", ""),
                        entry.get("at", ""),
                        entry.get("duration_ms"),
                    ),
                )

    # ------------------------------------------------------------------ 读
    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        """按结束时间倒序列出历史（轻量字段，不含报告正文）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, query, status, stop_reason, finished_at, duration_ms,
                       research_rounds, revision_count, usage_json, length(report) AS report_chars
                FROM runs ORDER BY finished_at DESC, rowid DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": r["run_id"],
                "query": r["query"],
                "status": r["status"],
                "stop_reason": r["stop_reason"],
                "finished_at": r["finished_at"],
                "duration_ms": r["duration_ms"],
                "research_rounds": r["research_rounds"],
                "revision_count": r["revision_count"],
                "usage": json.loads(r["usage_json"] or "{}"),
                "report_chars": r["report_chars"],
            }
            for r in rows
        ]

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            steps = conn.execute(
                "SELECT agent, action, at, duration_ms FROM steps WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return {
            "run_id": row["run_id"],
            "query": row["query"],
            "status": row["status"],
            "stop_reason": row["stop_reason"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "approved": bool(row["approved"]),
            "revision_count": row["revision_count"],
            "research_rounds": row["research_rounds"],
            "report": row["report"],
            "analysis": row["analysis"],
            "critique": row["critique"],
            "plan": json.loads(row["plan_json"] or "[]"),
            "failures": json.loads(row["failures_json"] or "{}"),
            "sources": json.loads(row["sources_json"] or "[]"),
            "usage": json.loads(row["usage_json"] or "{}"),
            "history": [dict(s) for s in steps],
            "error": row["error"],
            "archived": True,  # 与实时记录区分：这条来自数据库
        }

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
