"""FastAPI 后端：把 core 暴露成 HTTP + SSE，供网页与桌面窗口使用。

端点
----
GET  /                             web/index.html（同源，无 CORS 问题）
GET  /api/health                   健康检查
GET  /api/runs                     最近运行列表
POST /api/runs                     {"query": "..."} → {"run_id": "..."}
GET  /api/runs/{run_id}            运行快照（状态 / 报告 / 用量 / 失败项 / 来源）
GET  /api/runs/{run_id}/events     SSE 事件流（含缓冲回放，断线重连不丢事件）
POST /api/runs/{run_id}/cancel     请求取消（在**步骤边界**生效）

运行
----
python -m app.api                  # 真实调用（需要 .env 里的 LLM/搜索 key）
python -m app.api --demo           # 离线演示：桩客户端 + 真实流水线，不联网、不花 token
python -m app.api --port 8756      # 换端口

已知限制（M4 处理）
------------------
`core.llm.USAGE` 是**进程级**计量器、每次运行前 reset，所以同时只允许一个运行；
并发请求返回 409。M4 会把它改成「按运行独立计量」。
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.orchestrator import run_swarm
from core.state import SwarmState
from service.events import QueueSink, RunEvent

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DEFAULT_PORT = 8756
MAX_KEPT_RUNS = 50


class RunRequest(BaseModel):
    """POST /api/runs 的请求体。"""

    query: str = Field(min_length=1, max_length=500)


@dataclass
class RunRecord:
    """一次运行的完整记录：事件缓冲 + 最终状态 + 取消信号。"""

    run_id: str
    query: str
    status: str = "running"  # running | finished | cancelled | failed
    events: list[RunEvent] = field(default_factory=list)
    state: SwarmState | None = None
    error: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def stop_reason(self) -> str:
        for event in reversed(self.events):
            if event.type == "run_finished":
                return str(event.data.get("stop_reason", ""))
        return "cancelled" if self.status == "cancelled" else ""

    def summary(self) -> dict[str, Any]:
        """列表用的轻量快照。"""
        with self.lock:
            state = self.state
            return {
                "run_id": self.run_id,
                "query": self.query,
                "status": self.status,
                "stop_reason": self.stop_reason,
                "event_count": len(self.events),
                "duration_ms": state.duration_ms if state is not None else None,
                "error": self.error,
            }

    def detail(self) -> dict[str, Any]:
        """详情快照：给前端渲染报告与统计用。"""
        payload = self.summary()
        state = self.state
        if state is None:
            return payload
        payload.update(
            {
                "started_at": state.started_at,
                "cancelled": state.cancelled,
                "plan": list(state.plan),
                "report": state.draft,
                "analysis": state.analysis,
                "critique": state.critique,
                "approved": state.is_approved,
                "revision_count": state.revision_count,
                "research_rounds": state.research_rounds,
                "failures": dict(state.failures),
                "findings": {task: len(text) for task, text in state.findings.items()},
                "sources": [{"title": s.title, "url": s.url} for s in state.sources],
                "usage": asdict(state.usage),
                "history": [
                    {
                        "agent": h.agent,
                        "action": h.action,
                        "at": h.at,
                        "duration_ms": h.duration_ms,
                    }
                    for h in state.history
                ],
            }
        )
        return payload


class RunRegistry:
    """内存运行注册表（M4 会换成 SQLite 持久化）。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def create(self, query: str) -> RunRecord:
        record = RunRecord(run_id=uuid.uuid4().hex[:12], query=query)
        with self._lock:
            self._runs[record.run_id] = record
            self._order.append(record.run_id)
            while len(self._order) > MAX_KEPT_RUNS:
                self._runs.pop(self._order.pop(0), None)
        return record

    def get(self, run_id: str) -> RunRecord:
        with self._lock:
            record = self._runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"未知 run_id: {run_id}")
        return record

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            records = [self._runs[i] for i in reversed(self._order) if i in self._runs]
        return [r.summary() for r in records]

    def active(self) -> RunRecord | None:
        """当前正在跑的运行（进程级计量器决定了同时只能有一个）。"""
        with self._lock:
            records = [self._runs[i] for i in self._order if i in self._runs]
        for record in records:
            if record.status == "running":
                return record
        return None


registry = RunRegistry()


def _run_worker(record: RunRecord, sink: QueueSink) -> None:
    """在工作线程里跑一次编排：事件同时写入缓冲（供回放）与 sink（供推送）。"""

    def on_event(event: RunEvent) -> None:
        with record.lock:
            record.events.append(event)
        sink(event)

    try:
        state = run_swarm(record.query, on_event=on_event, cancel=record.cancel)
    except Exception as exc:  # noqa: BLE001 - 后台线程必须兜住一切，否则异常无处可去
        with record.lock:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
    else:
        with record.lock:
            record.state = state
            record.status = "cancelled" if state.cancelled else "finished"
    finally:
        record.finished.set()
        sink.close()  # 结束所有 SSE 流


app = FastAPI(title="ResearchSwarm API", version="0.2.0")


@app.get("/api/health")
def health() -> dict[str, Any]:
    active = registry.active()
    return {"ok": True, "active_run": active.run_id if active is not None else None}


@app.get("/api/runs")
def list_runs() -> dict[str, Any]:
    return {"runs": registry.list()}


@app.post("/api/runs", status_code=201)
def create_run(request: RunRequest) -> dict[str, Any]:
    active = registry.active()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=f"已有运行在进行中（{active.run_id}）；进程级 token 计量器暂不支持并发",
        )
    record = registry.create(request.query.strip())
    sink = QueueSink()
    threading.Thread(
        target=_run_worker,
        args=(record, sink),
        name=f"swarm-{record.run_id}",
        daemon=True,
    ).start()
    return {"run_id": record.run_id, "status": record.status}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return registry.get(run_id).detail()


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    record = registry.get(run_id)
    if record.status != "running":
        return {"ok": False, "status": record.status}
    record.cancel.set()
    return {"ok": True, "status": "cancelling"}


@app.get("/api/runs/{run_id}/events")
def stream_events(run_id: str) -> StreamingResponse:
    """SSE：先回放已产生的事件，再增量推送，最后发一个 end 帧。"""
    record = registry.get(run_id)

    def generate() -> Iterator[str]:
        sent = 0
        while True:
            with record.lock:
                pending = record.events[sent:]
                sent += len(pending)
                done = record.finished.is_set()
            for event in pending:
                payload = json.dumps(event.to_dict(), ensure_ascii=False)
                yield f"data: {payload}\n\n"
            if done and not pending:
                break
            if not pending:
                time.sleep(0.05)
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# 静态前端挂到最后：Starlette 按注册顺序匹配，所以 /api/* 不会被它抢走。
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def enable_demo_mode() -> None:
    """装上离线桩：真实流水线 + 假 LLM/搜索（不联网、不花 token）。"""
    from scripts import demo_offline

    demo_offline._install_fake_llm()
    demo_offline._install_fake_search()


def main() -> None:
    parser = argparse.ArgumentParser(description="ResearchSwarm 本地服务（HTTP + SSE）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--demo", action="store_true", help="离线演示模式（不调用真实 API）")
    args = parser.parse_args()

    if args.demo:
        enable_demo_mode()

    import uvicorn

    suffix = "（离线演示模式）" if args.demo else ""
    print(f"ResearchSwarm 服务已启动：http://{args.host}:{args.port}/{suffix}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
