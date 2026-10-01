"""运行事件契约与取消机制的测试（M1 的验收标准）。

已完成的范例在下面，**5 个 TODO 由你实现**（都用 `pytest.mark.skip` 标着，
所以在你动手前测试基线保持全绿，不会挡住 CI）。

规格细节见 `docs/ui-plan.md` 的「事件契约」与「取消语义」两节。要点：
- 事件序列：run_started → step_started/step_finished ×N →（可选 round_* / rewrite_started）→ run_finished
- 取消在**步骤边界**生效：置位后不再执行后续 Agent，已完成产出保留，并发出 run_cancelled
- run_finished 的 `data.stop_reason` 区分 `approved` / `max_revisions` / `finished`

跑测试：`pytest tests/test_events.py -q`（`-k TODO` 之外的全都会跑）
"""

from __future__ import annotations

import threading

import pytest

from agents import real_agents
from core import orchestrator
from service.events import RunEvent, null_sink
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
) -> tuple[object, list[RunEvent]]:
    """跑一次离线流程，返回 (state, [事件...])。"""
    _install_offline_stubs(monkeypatch)
    events: list[RunEvent] = []
    state = orchestrator.run_swarm("事件契约测试", on_event=events.append, cancel=cancel)
    return state, events


# --------------------------------------------------------------------- 范例
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


# ----------------------------------------------------------------- 你的任务
@pytest.mark.skip(reason="TODO(用户): 事件配对与顺序")
def test_steps_are_paired_and_ordered(monkeypatch):
    """断言：

    1. 每个 `step_started` 都紧跟着同 agent 的 `step_finished`（数量相等、名字一一对应）；
    2. **首次执行**的 agent 顺序是 Planner → Researcher → Analyst → Writer → Critic；
    3. 每条 `step_finished.duration_ms >= 0`；
    4. 每条 `step_finished.data["usage"]["calls"]` 是整数（用量快照可用）。
    """


@pytest.mark.skip(reason="TODO(用户): 取消在 Analyst 之后生效")
def test_cancel_stops_before_writer(monkeypatch):
    """用一个 sink：收到 Analyst 的 `step_finished` 时 `cancel.set()`。断言：

    1. `state.cancelled is True`；
    2. 事件流最后一条是 `run_cancelled`；
    3. 没有任何 `agent == "Writer"` 的事件；
    4. 取消前已完成的产出仍在（例如 `state.plan` 非空、`state.analysis` 非空）。
    """


@pytest.mark.skip(reason="TODO(用户): 一开始就取消")
def test_cancel_before_planner_produces_no_steps(monkeypatch):
    """构造一个**已置位**的 `threading.Event()` 传进去，断言：

    1. `state.cancelled is True`；
    2. 事件序列恰为 `["run_started", "run_cancelled"]`；
    3. `state.history == []`（一步都没跑）。
    """


@pytest.mark.skip(reason="TODO(用户): QueueSink 跨线程投递（M2 SSE 的基础）")
def test_queue_sink_delivers_events_across_threads(monkeypatch):
    """在**子线程**里跑 `run_swarm`，主线程用 `QueueSink.iter_events()` 收集。断言：

    1. 收到的事件与直接 `list.append` 时**数量和类型序列一致**；
    2. 第一条是 `run_started`；
    3. 收完记得 `sink.close()` —— 否则 `iter_events()` 会永远阻塞（用 `thread.join(timeout=…)` 兜底）。

    提示：`from service.events import QueueSink`
    """


@pytest.mark.skip(reason="TODO(用户): to_sink 的入参兼容性")
def test_to_sink_accepts_none_callable_and_sink():
    """断言：`to_sink(None)` 返回可调用对象且调用不抛异常；
    `to_sink(lambda e: None)` 返回该可调用对象；`to_sink(123)` 抛 `TypeError`。

    提示：`from service.events import to_sink`
    """


def test_null_sink_is_callable():
    """参考实现：null_sink 就是「丢掉事件」，不应该抛异常。"""
    null_sink(RunEvent(type="run_started", at="2026-01-01T00:00:00+08:00"))
