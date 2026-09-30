from dataclasses import dataclass, field
from typing import Any


@dataclass
class SwarmState:
    """所有 Agent 共享的状态"""
    # 用户的问题
    query: str = ""

    # Planner 产出：子任务列表
    plan: list[str] = field(default_factory=list)

    # Researcher 产出：每个子任务的调研结果
    findings: dict[str, str] = field(default_factory=dict)

    # Analyst 产出：综合分析
    analysis: str = ""

    # Writer 产出：报告草稿
    draft: str = ""

    # Critic 产出：评审意见
    critique: str = ""
    is_approved: bool = False

    # 迭代控制
    revision_count: int = 0
    MAX_REVISIONS: int = 2

    # 执行日志（谁在什么时候做了什么）
    history: list[dict[str, Any]] = field(default_factory=list)

    def log(self, agent: str, action: str):
        self.history.append({"agent": agent, "action": action})
        