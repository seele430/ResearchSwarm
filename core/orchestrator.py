"""
Orchestrator - 编排所有 Agent 的执行顺序
"""

from core.state import SwarmState
from agents.real_agents import (
    planner_agent,
    researcher_agent,
    analyst_agent,
    writer_agent,
    critic_agent,
)

def run_swarm(query: str, verbose: bool = True) -> SwarmState:
    """执行完整的多 Agent 流水线"""
    state = SwarmState(query=query)

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"🚀 ResearchSwarm 启动")
        print(f"📝 用户问题：{query}")
        print(f"{'=' * 60}\n")

    # ---- 阶段 1：规划 ----
    _run_step("Planner", planner_agent, state, verbose)

    # ---- 阶段 2：调研 ----
    _run_step("Researcher", researcher_agent, state, verbose)

    # ---- 阶段 3：分析 ----
    _run_step("Analyst", analyst_agent, state, verbose)

    # ---- 阶段 4：撰写 + 评审循环 ----
    while True:
        _run_step("Writer", writer_agent, state, verbose)
        _run_step("Critic", critic_agent, state, verbose)

        if state.is_approved:
            if verbose:
                print("✅ Critic 通过，任务结束\n")
            break

        if state.revision_count >= state.MAX_REVISIONS:
            if verbose:
                print(f"⚠️  达到最大修改次数 {state.MAX_REVISIONS}，强制结束\n")
            break

        if verbose:
            print(f"🔄 打回重写（第 {state.revision_count} 次修改）\n")

    return state


def _run_step(agent_name: str, agent_func, state: SwarmState, verbose: bool):
    """执行单个 Agent"""
    if verbose:
        print(f"▶️  [{agent_name}] 执行中...")
    agent_func(state)