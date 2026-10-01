"""Orchestrator - 编排所有 Agent 的执行顺序，并记录每步耗时与 LLM 用量。

执行图（注意那条**回边**，它让系统不只是单向流水线）：

    Planner → Researcher → Analyst ─┬─→ Writer ⇄ Critic
                ▲                    │
                └──── Planner(补研) ─┘   当 Analyst 报出信息缺口、或存在调研失败时
                                         （最多 MAX_RESEARCH_ROUNDS 轮）
"""

from __future__ import annotations

import time

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


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def run_swarm(query: str, verbose: bool = True) -> SwarmState:
    """执行完整的多 Agent 流水线（含补研回边与评审闭环）。"""
    state = SwarmState(query=query)
    USAGE.reset()
    state.started_at = now_iso()
    run_started = time.perf_counter()

    if verbose:
        print(f"\n{'=' * 60}")
        print("🚀 ResearchSwarm 启动")
        print(f"📝 用户问题：{query}")
        print(f"{'=' * 60}\n")

    # ---- 阶段 1-3：规划 → 调研 → 分析 ----
    _run_step("Planner", planner_agent, state, verbose)
    _run_step("Researcher", researcher_agent, state, verbose)
    _run_step("Analyst", analyst_agent, state, verbose)

    # ---- 回边：缺口/失败 → 补研一轮（Analyst 发现缺口，Planner 改计划）----
    while (state.gaps or state.failures) and state.research_rounds < state.MAX_RESEARCH_ROUNDS:
        state.research_rounds += 1
        if verbose:
            print(
                f"🔁 第 {state.research_rounds} 轮补充调研"
                f"（缺口 {len(state.gaps)} 条 / 失败 {len(state.failures)} 项）\n"
            )

        plan_before = list(state.plan)
        _run_step("Planner(补研)", planner_extend_agent, state, verbose)

        retry_tasks = list(state.failures)
        new_tasks = [t for t in state.plan if t not in plan_before]
        targets = new_tasks + [t for t in retry_tasks if t not in new_tasks]
        for task in targets:
            state.failures.pop(task, None)  # 允许重新判定成败

        if not targets:
            if verbose:
                print("   （没有可补研的子任务，结束回边）\n")
            break

        _run_step(
            "Researcher(补研)",
            lambda s, tasks=targets: researcher_agent(s, tasks=tasks),
            state,
            verbose,
        )
        _run_step("Analyst(复评)", analyst_agent, state, verbose)

    # ---- 阶段 4：撰写 + 评审循环 ----
    while True:
        _run_step("Writer", writer_agent, state, verbose)
        _run_step("Critic", critic_agent, state, verbose)

        if state.is_approved:
            if verbose:
                print("✅ Critic 通过，任务结束\n")
            break

        # revision_count 表示「已经发生的重写次数」，在此处推进：
        # MAX_REVISIONS=2 → Writer 最多被调用 3 次（初稿 + 2 次重写）。
        if state.revision_count >= state.MAX_REVISIONS:
            if verbose:
                print(f"⚠️  已达到最大重写次数 {state.MAX_REVISIONS}，强制结束\n")
            break

        state.revision_count += 1
        if verbose:
            print(f"🔄 打回重写（第 {state.revision_count}/{state.MAX_REVISIONS} 次）\n")

    state.duration_ms = _elapsed_ms(run_started)
    state.usage = USAGE.snapshot()
    return state


def _run_step(agent_name: str, agent_func, state: SwarmState, verbose: bool = True) -> int:
    """执行单个 Agent，并把耗时记入执行日志。返回耗时（毫秒）。"""
    if verbose:
        print(f"▶️  [{agent_name}] 执行中...")

    started = time.perf_counter()
    agent_func(state)
    elapsed = _elapsed_ms(started)

    state.log(agent_name, "步骤完成", duration_ms=elapsed)
    if verbose:
        print(f"   ⏱  [{agent_name}] {elapsed / 1000:.1f}s")
    return elapsed
