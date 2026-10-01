"""Orchestrator - 编排所有 Agent 的执行顺序，并记录每步耗时与 LLM 用量。

执行图（注意那条**回边**，它让系统不只是单向流水线）：

    Planner → Researcher → Analyst ─┬─→ Writer ⇄ Critic
                ▲                    │
                └──── Planner(补研) ─┘   当 Analyst 报出信息缺口、或存在调研失败时
                                         （最多 MAX_RESEARCH_ROUNDS 轮）

本模块**不再 print**：进度以结构化事件流输出（见 `service/events.py`），
CLI / FastAPI / 桌面窗口各自决定怎么渲染。取消通过 `threading.Event` 在**步骤边界**生效。
"""

from __future__ import annotations

import time
from dataclasses import asdict
from threading import Event

from agents.real_agents import (
    analyst_agent,
    critic_agent,
    planner_agent,
    planner_extend_agent,
    researcher_agent,
    writer_agent,
)
from core.llm import USAGE
from core.state import SwarmState, now_iso
from service.events import EventSink, RunEvent, event_now, to_sink


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _usage_dict() -> dict[str, int]:
    """当次 LLM 用量快照（可 JSON 序列化）。"""
    return asdict(USAGE.snapshot())


def run_swarm(
    query: str,
    verbose: bool = False,
    on_event: EventSink | None = None,
    cancel: Event | None = None,
) -> SwarmState:
    """执行完整的多 Agent 流水线（含补研回边与评审闭环）。

    参数
    ----
    verbose : **已废弃**。进度改为事件流；保留该参数只为兼容既有调用与测试。
    on_event: 事件出口（函数或 sink 对象）；传 None 表示不关心进度。
    cancel  : 可选取消信号。在**步骤边界**检查，置位后尽快返回：
              已完成的步骤与产出全部保留，不打断正在进行的 LLM 调用。
    """
    sink = to_sink(on_event)
    state = SwarmState(query=query)
    USAGE.reset()
    state.started_at = now_iso()
    run_started = time.perf_counter()

    sink(
        RunEvent(
            type="run_started",
            at=event_now(),
            data={"query": query, "started_at": state.started_at},
        )
    )

    def cancelled(stage: str) -> bool:
        """若取消信号已置位：落状态、发事件，并告诉调用方立刻返回。"""
        if cancel is None or not cancel.is_set():
            return False
        state.cancelled = True
        state.duration_ms = _elapsed_ms(run_started)
        state.usage = USAGE.snapshot()
        sink(
            RunEvent(
                type="run_cancelled",
                at=event_now(),
                duration_ms=state.duration_ms,
                data={"stage": stage},
            )
        )
        return True

    # ---- 阶段 1-3：规划 → 调研 → 分析 ----
    first_legs = (
        ("planner", "Planner", planner_agent),
        ("researcher", "Researcher", researcher_agent),
        ("analyst", "Analyst", analyst_agent),
    )
    for stage, name, func in first_legs:
        if cancelled(f"before_{stage}"):
            return state
        _run_step(name, func, state, sink)

    # ---- 回边：缺口/失败 → 补研一轮（Analyst 发现缺口，Planner 改计划）----
    while (state.gaps or state.failures) and state.research_rounds < state.MAX_RESEARCH_ROUNDS:
        if cancelled("before_replan"):
            return state

        state.research_rounds += 1
        sink(
            RunEvent(
                type="round_started",
                at=event_now(),
                data={
                    "round": state.research_rounds,
                    "gaps": list(state.gaps),
                    "failures": list(state.failures),
                },
            )
        )

        plan_before = list(state.plan)
        _run_step("Planner(补研)", planner_extend_agent, state, sink)

        retry_tasks = list(state.failures)
        new_tasks = [t for t in state.plan if t not in plan_before]
        targets = new_tasks + [t for t in retry_tasks if t not in new_tasks]
        for task in targets:
            state.failures.pop(task, None)  # 允许重新判定成败

        if not targets:
            sink(RunEvent(type="round_skipped", at=event_now(), data={"reason": "no_targets"}))
            break

        if cancelled("before_replan_research"):
            return state
        _run_step(
            "Researcher(补研)",
            lambda s, tasks=targets: researcher_agent(s, tasks=tasks),
            state,
            sink,
        )
        _run_step("Analyst(复评)", analyst_agent, state, sink)

    # ---- 阶段 4：撰写 + 评审循环 ----
    stop_reason = "finished"
    while True:
        if cancelled("before_writer"):
            return state
        _run_step("Writer", writer_agent, state, sink)

        if cancelled("before_critic"):
            return state
        _run_step("Critic", critic_agent, state, sink)

        if state.is_approved:
            stop_reason = "approved"
            break

        # revision_count 表示「已经发生的重写次数」，在此处推进：
        # MAX_REVISIONS=2 → Writer 最多被调用 3 次（初稿 + 2 次重写）。
        if state.revision_count >= state.MAX_REVISIONS:
            stop_reason = "max_revisions"
            break

        state.revision_count += 1
        sink(
            RunEvent(
                type="rewrite_started",
                at=event_now(),
                data={"revision": state.revision_count, "max_revisions": state.MAX_REVISIONS},
            )
        )

    state.duration_ms = _elapsed_ms(run_started)
    state.usage = USAGE.snapshot()
    sink(
        RunEvent(
            type="run_finished",
            at=event_now(),
            duration_ms=state.duration_ms,
            data={
                "stop_reason": stop_reason,
                "approved": state.is_approved,
                "revision_count": state.revision_count,
                "research_rounds": state.research_rounds,
                "usage": asdict(state.usage),
                "failures": dict(state.failures),
                "sources": len(state.sources),
            },
        )
    )
    return state


def _run_step(agent_name: str, agent_func, state: SwarmState, sink: EventSink) -> int:
    """执行单个 Agent，发出 step_started / step_finished，并把耗时记入执行日志。"""
    sink(RunEvent(type="step_started", at=event_now(), agent=agent_name))

    started = time.perf_counter()
    agent_func(state)
    elapsed = _elapsed_ms(started)

    entry = state.log(agent_name, "步骤完成", duration_ms=elapsed)
    sink(
        RunEvent(
            type="step_finished",
            at=entry.at,
            agent=agent_name,
            duration_ms=elapsed,
            data={
                "usage": _usage_dict(),
                "plan": len(state.plan),
                "findings": len(state.findings),
            },
        )
    )
    return elapsed
