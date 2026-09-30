"""
Mock Agents - 用于 Day 1 验证状态机流转
每个 Agent 只做简单操作，不调用 LLM
"""

from core.state import SwarmState


def planner_agent(state: SwarmState):
    """Planner：把问题拆解成子任务"""
    state.log("Planner", "开始拆解任务")
    # 假装拆解出 3 个子任务
    state.plan = [
        f"调研 {state.query} 的背景",
        f"调研 {state.query} 的现状",
        f"调研 {state.query} 的趋势",
    ]
    state.log("Planner", f"拆解出 {len(state.plan)} 个子任务")


def researcher_agent(state: SwarmState):
    """Researcher：对每个子任务做调研"""
    state.log("Researcher", "开始调研")
    for task in state.plan:
        # 假装找到了内容
        state.findings[task] = f"[Mock] 关于「{task}」的调研结果..."
    state.log("Researcher", f"完成 {len(state.findings)} 项调研")


def analyst_agent(state: SwarmState):
    """Analyst：综合分析"""
    state.log("Analyst", "开始分析")
    # 把所有发现串起来
    state.analysis = "综合分析：\n" + "\n".join(
        f"- {k}: {v}" for k, v in state.findings.items()
    )
    state.log("Analyst", "分析完成")


def writer_agent(state: SwarmState):
    """Writer：撰写报告"""
    state.log("Writer", "开始撰写报告")
    state.draft = f"""# 关于「{state.query}」的研究报告

## 一、调研计划
{chr(10).join(f'{i+1}. {t}' for i, t in enumerate(state.plan))}

## 二、分析
{state.analysis}

## 三、结论
（此处为 Mock 内容，接入 LLM 后会生成真实报告）
"""
    state.log("Writer", f"报告完成，共 {len(state.draft)} 字")


def critic_agent(state: SwarmState):
    """Critic：评审报告质量"""
    state.log("Critic", "开始评审")
    # Mock：第一次打回，第二次通过
    if state.revision_count == 0:
        state.is_approved = False
        state.critique = "[Mock] 报告不够详细，请补充数据支撑"
        state.revision_count += 1
        state.log("Critic", "打回重写")
    else:
        state.is_approved = True
        state.critique = "[Mock] 报告合格"
        state.log("Critic", "通过")