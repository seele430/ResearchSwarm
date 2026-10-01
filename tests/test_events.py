"""运行事件契约与取消机制的测试（M1 的验收标准）。

覆盖：
- 事件信封（run_started / run_finished）与可 JSON 序列化
- step_started / step_finished 严格配对与首次执行顺序
- 取消在**步骤边界**生效：不执行后续 Agent、已完成产出保留
- 一开始就取消：只有 run_started + run_cancelled，且没有产生任何步骤
- QueueSink 跨线程投递（M2 SSR/SSE 的基础）
- to_sink 的入参兼容性

规格见 `docs/ui-plan.md` 的「事件契约」与「取消语义」两节。
"""

from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from agents import real_agents
from core import orchestrator
from core.state import SwarmState
from service.events import QueueSink, RunEvent, null_sink, to_sink
from tools import SearchResult


def _install_offline_stubs(monkeypatch) -> None:
    """把 LLM 与搜索换成确定性桩（完全不联网，与 test_pipeline_offline.py 同款）。"""

    def fake_chat(system_prompt, user_prompt, temperature=0.7):
        if "研究任务规划专家" in system_prompt:
            return '["调研背景", "调研现状"]'
        if "调研员" in system_prompt:
            return "子任务结论 [1]"
        if "研究分析师" in system_prompt:
            return '{"analysis": "综合分析 [1]", "gaps": []}'
        if "报告撰写专家" in system_prompt:
            return "# 研究报告\n\n## 结论\n结论 [1]。"
        if "质量评审员" in system_prompt:
            return '{"approved": true, "critique": "合格", "score": 9}'
        raise AssertionError(f"未预期的 system prompt: {system_prompt[:40]}")

    counter = {"n": 0}

    def fake_search(task, max_results=5):
        counter["n"] += 1
        return [
            SearchResult(
                title=f"{task} 来源",
                url=f"https://example.com/{counter['n']}",
                snippet="摘要",
            )
        ]

    monkeypatch.setattr(real_agents, "chat", fake_chat)
    monkeypatch.setattr(real_agents, "web_search", fake_search)
    monkeypatch.setattr(real_agents, "read_url", lambda url, **kwargs: f"{url} 正文")


def _collect_events(
    monkeypatch, cancel: threading.Event | None = None
) -> tuple[SwarmState, list[RunEvent]]:
    """跑一次离线流程，返回 (state, [事件...])。"""
    _install_offline_stubs(monkeypatch)
    events: list[RunEvent] = []
    state = orchestrator.run_swarm("事件契约测试", on_event=events.append, cancel=cancel)
    return state, events


def _agents_of(events: list[RunEvent], kind: str) -> list[str]:
    return [str(e.agent) for e in events if e.type == kind]


# --------------------------------------------------------------------- 基本契约
def test_emits_run_started_then_run_finished(monkeypatch):
    """最小完整断言：首尾事件、stop_reason、耗时、未被取消。"""
    state, events = _collect_events(monkeypatch)

    assert events[0].type == "run_started"
    assert events[0].data["query"] == "事件契约测试"
    assert events[-1].type == "run_finished"
    assert events[-1].data["stop_reason"] == "approved"
    assert events[-1].duration_ms is not None and events[-1].duration_ms >= 0
    assert state.cancelled is False

    # 事件可以直接给前端用（M2 的 SSE 依赖这个）
    payload = events[-1].to_dict()
    assert payload["type"] == "run_finished" and isinstance(payload["data"], dict)


def test_steps_are_paired_and_ordered(monkeypatch):
    """每个 step_started 都有同 agent 的 step_finished，且首次执行顺序正确。"""
    _, events = _collect_events(monkeypatch)

    started = _agents_of(events, "step_started")
    finished = _agents_of(events, "step_finished")
    assert started == finished, "step_started / step_finished 必须一一对应且顺序一致"
    assert started[:5] == ["Planner", "Researcher", "Analyst", "Writer", "Critic"]

    for event in events:
        if event.type == "step_finished":
            assert event.duration_ms is not None and event.duration_ms >= 0
            assert isinstance(event.data["usage"]["calls"], int)


# ------------------------------------------------------------------------- 取消
def test_cancel_stops_before_writer(monkeypatch):
    """Analyst 结束时取消：不进入 Writer，已完成的产出保留。"""
    _install_offline_stubs(monkeypatch)
    cancel = threading.Event()
    events: list[RunEvent] = []

    def sink(event: RunEvent) -> None:
        events.append(event)
        if event.type == "step_finished" and event.agent == "Analyst":
            cancel.set()

    state = orchestrator.run_swarm("取消测试", on_event=sink, cancel=cancel)

    assert state.cancelled is True
    assert events[-1].type == "run_cancelled"
    assert events[-1].data["stage"] == "before_writer"
    assert "Writer" not in _agents_of(events, "step_started")
    # 取消前完成的产出仍然在
    assert state.plan and state.analysis


def test_cancel_before_planner_produces_no_steps(monkeypatch):
    """一开始就取消：只有 run_started + run_cancelled，一步都没跑。"""
    _install_offline_stubs(monkeypatch)
    cancel = threading.Event()
    cancel.set()
    events: list[RunEvent] = []

    state = orchestrator.run_swarm("预先取消", on_event=events.append, cancel=cancel)

    assert [event.type for event in events] == ["run_started", "run_cancelled"]
    assert events[-1].data["stage"] == "before_planner"
    assert state.cancelled is True
    assert state.history == []
    assert state.draft == ""


# ------------------------------------------------------------------- sink 行为
def test_queue_sink_delivers_events_across_threads(monkeypatch):
    """子线程跑编排、主线程 iter_events() 收集；序列要与直接收集的一致。"""
    _install_offline_stubs(monkeypatch)
    sink = QueueSink()

    def worker() -> None:
        orchestrator.run_swarm("跨线程测试", on_event=sink)
        sink.close()  # 不 close 的话 iter_events() 会一直等

    thread = threading.Thread(target=worker, name="swarm-worker")
    thread.start()
    collected = list(sink.iter_events())  # 阻塞直到收到哨兵
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert collected[0].type == "run_started"
    assert collected[-1].type == "run_finished"

    _, direct = _collect_events(monkeypatch)
    assert [e.type for e in collected] == [e.type for e in direct]


def test_to_sink_accepts_none_callable_and_sink():
    """None / 普通函数 / sink 对象都能用；其它类型要明确报错。"""
    event = RunEvent(type="run_started", at="2026-01-01T00:00:00+08:00")

    to_sink(None)(event)  # 不抛异常即可

    received: list[RunEvent] = []
    to_sink(received.append)(event)
    assert received == [event]

    queue_sink = QueueSink()
    to_sink(queue_sink)(event)
    assert queue_sink.get(timeout=1) == event
    queue_sink.close()
    assert queue_sink.get(timeout=1) is None  # 哨兵：流已结束

    with pytest.raises(TypeError):
        to_sink(123)  # type: ignore[arg-type]


def test_null_sink_is_callable():
    """null_sink 就是「丢掉事件」，不应该抛异常。"""
    null_sink(RunEvent(type="run_started", at="2026-01-01T00:00:00+08:00"))


def test_event_dataclass_is_frozen():
    """事件是跨线程传递的不可变快照。"""
    event = RunEvent(type="run_started", at="2026-01-01T00:00:00+08:00", data={"a": 1})
    with pytest.raises(FrozenInstanceError):
        event.type = "run_finished"  # type: ignore[misc]


def test_usage_snapshot_is_json_serializable(monkeypatch):
    """step_finished 里带出的用量快照必须是纯数据（能直接进 JSON/SSE）。"""
    _, events = _collect_events(monkeypatch)
    finished = [e for e in events if e.type == "step_finished"]
    assert finished
    usage: Any = finished[-1].data["usage"]
    assert set(usage) >= {"prompt_tokens", "completion_tokens", "total_tokens", "calls"}
    assert all(isinstance(v, int) for v in usage.values())
