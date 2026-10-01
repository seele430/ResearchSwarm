"""所有 Agent 共享的状态与观测数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import ClassVar


def now_iso() -> str:
    """本地时区的 ISO 时间戳（带时区偏移，避免 naive datetime）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class SourceRef:
    """一条可核验的来源（URL 来自搜索 API，不由模型编造）。"""

    title: str
    url: str
    task: str = ""


@dataclass(frozen=True)
class HistoryEntry:
    """执行日志条目：谁、什么时候、做了什么、花了多久。"""

    agent: str
    action: str
    at: str
    duration_ms: int | None = None


@dataclass(frozen=True)
class UsageStat:
    """一次运行累计的 LLM 用量（跨线程累加，由 core.llm 的计量器产出）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0


@dataclass
class SwarmState:
    """所有 Agent 共享的状态"""

    # 迭代上限是「配置常量」，不属于某一次运行的数据：
    # 用 ClassVar 声明，避免它被写进每次运行的状态快照 / 序列化结果里。
    MAX_REVISIONS: ClassVar[int] = 2

    # 用户的问题
    query: str = ""

    # Planner 产出：子任务列表
    plan: list[str] = field(default_factory=list)

    # Researcher 产出：每个子任务的调研结果
    findings: dict[str, str] = field(default_factory=dict)

    # 调研失败的子任务 → 失败原因（失败必须显式入账，不能伪装成"调研结果"）
    failures: dict[str, str] = field(default_factory=dict)

    # 本轮用到的全部来源（按 URL 去重，保持首次出现顺序）。
    # 报告末尾的「参考来源」直接由它生成 —— 链接来自搜索 API，不经过模型。
    sources: list[SourceRef] = field(default_factory=list)

    # Analyst 产出：综合分析
    analysis: str = ""

    # Writer 产出：报告草稿
    draft: str = ""

    # Critic 产出：评审意见
    critique: str = ""
    is_approved: bool = False

    # 迭代控制：已经发生的「重写」次数（由编排器推进，Critic 只负责判定）
    revision_count: int = 0

    # 补研控制：Analyst 报出信息缺口后，最多再补一轮调研
    MAX_RESEARCH_ROUNDS: ClassVar[int] = 1
    research_rounds: int = 0

    # Analyst 报出的信息缺口（被补研规划消费后清空）
    gaps: list[str] = field(default_factory=list)

    # 观测数据
    started_at: str = ""
    duration_ms: int = 0
    usage: UsageStat = field(default_factory=UsageStat)

    # 执行日志（谁在什么时候做了什么，步骤级条目带耗时）
    history: list[HistoryEntry] = field(default_factory=list)

    def log(self, agent: str, action: str, *, duration_ms: int | None = None) -> HistoryEntry:
        """记录一条执行日志，返回该条目。"""
        entry = HistoryEntry(
            agent=agent,
            action=action,
            at=now_iso(),
            duration_ms=duration_ms,
        )
        self.history.append(entry)
        return entry

    def step_durations(self) -> dict[str, int]:
        """按 agent 汇总步骤耗时（毫秒）——性能数据直接取自这里。"""
        durations: dict[str, int] = {}
        for entry in self.history:
            if entry.duration_ms is None:
                continue
            durations[entry.agent] = durations.get(entry.agent, 0) + entry.duration_ms
        return durations

    def with_usage(self, usage: UsageStat) -> SwarmState:
        return replace(self, usage=usage)
