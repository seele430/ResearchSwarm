"""评审（Writer ⇄ Critic）循环的语义测试。

历史 bug：`critic_agent` 每次调用都 `revision_count += 1`（通过时也加），
配合编排器里的 `revision_count >= MAX_REVISIONS` 判断，
导致 `MAX_REVISIONS = 2` 实际只重写了 **1** 次 —— 与 README/DECISIONS 的说法不一致。

这里把语义钉死：**MAX_REVISIONS = 最多重写几次**，即 Writer 最多被调用 MAX_REVISIONS+1 次。
"""

from agents import real_agents
from core import orchestrator
from core.state import SwarmState


def _install_fake_agents(monkeypatch, approve_on_calls: set[int], writer_calls: list[int]):
    """把 5 个 agent 换成脚本化假实现，只保留编排逻辑在测试范围内。"""

    def fake_planner(state: SwarmState) -> None:
        state.plan = ["子任务1", "子任务2"]

    def fake_researcher(state: SwarmState) -> None:
        state.findings = {"子任务1": "结果1", "子任务2": "结果2"}

    def fake_analyst(state: SwarmState) -> None:
        state.analysis = "分析"

    def fake_writer(state: SwarmState) -> None:
        writer_calls.append(state.revision_count)
        state.draft = f"草稿 {len(writer_calls)}"

    def fake_critic(state: SwarmState) -> None:
        # 第 n 次 Writer 之后被调用；approve_on_calls 决定第几次放行
        state.is_approved = len(writer_calls) in approve_on_calls
        state.critique = "[评分: 7] 论据不足"

    monkeypatch.setattr(orchestrator, "planner_agent", fake_planner)
    monkeypatch.setattr(orchestrator, "researcher_agent", fake_researcher)
    monkeypatch.setattr(orchestrator, "analyst_agent", fake_analyst)
    monkeypatch.setattr(orchestrator, "writer_agent", fake_writer)
    monkeypatch.setattr(orchestrator, "critic_agent", fake_critic)


def test_never_approved_rewrites_exactly_max_revisions_times(monkeypatch):
    writer_calls: list[int] = []
    _install_fake_agents(monkeypatch, approve_on_calls=set(), writer_calls=writer_calls)

    state = orchestrator.run_swarm("测试问题", verbose=False)

    assert len(writer_calls) == SwarmState.MAX_REVISIONS + 1, "应为「初稿 + MAX_REVISIONS 次重写」"
    assert state.revision_count == SwarmState.MAX_REVISIONS
    assert state.is_approved is False


def test_approved_on_first_pass_stops_immediately(monkeypatch):
    writer_calls: list[int] = []
    _install_fake_agents(monkeypatch, approve_on_calls={1}, writer_calls=writer_calls)

    state = orchestrator.run_swarm("测试问题", verbose=False)

    assert len(writer_calls) == 1
    assert state.revision_count == 0
    assert state.is_approved is True


def test_approved_on_second_pass_counts_one_revision(monkeypatch):
    writer_calls: list[int] = []
    _install_fake_agents(monkeypatch, approve_on_calls={2}, writer_calls=writer_calls)

    state = orchestrator.run_swarm("测试问题", verbose=False)

    assert len(writer_calls) == 2
    assert state.revision_count == 1
    assert state.is_approved is True


def test_revision_count_advances_before_each_rewrite(monkeypatch):
    """重写时 Writer 看到的 revision_count 应当是已发生的重写次数（1、2…）。"""
    writer_calls: list[int] = []
    _install_fake_agents(monkeypatch, approve_on_calls=set(), writer_calls=writer_calls)

    orchestrator.run_swarm("测试问题", verbose=False)

    assert writer_calls == [0, 1, 2]


def test_max_revisions_is_configurable(monkeypatch):
    monkeypatch.setattr(SwarmState, "MAX_REVISIONS", 0)
    writer_calls: list[int] = []
    _install_fake_agents(monkeypatch, approve_on_calls=set(), writer_calls=writer_calls)

    state = orchestrator.run_swarm("测试问题", verbose=False)

    assert len(writer_calls) == 1, "MAX_REVISIONS=0 时不应发生重写"
    assert state.revision_count == 0


# ---------- Critic 本身的行为 ----------


def test_critic_does_not_move_revision_count(monkeypatch):
    """回归测试：Critic 只负责判定，不得推进 revision_count。"""
    monkeypatch.setattr(
        real_agents, "chat",
        lambda **_: '{"approved": false, "critique": "缺论据", "score": 6}',
    )
    state = SwarmState(query="q", draft="d")
    real_agents.critic_agent(state)

    assert state.is_approved is False
    assert state.revision_count == 0
    assert "6" in state.critique


def test_critic_parses_code_fenced_json(monkeypatch):
    monkeypatch.setattr(
        real_agents, "chat",
        lambda **_: '```json\n{"approved": true, "critique": "合格", "score": 9}\n```',
    )
    state = SwarmState(query="q", draft="d")
    real_agents.critic_agent(state)

    assert state.is_approved is True
    assert "9" in state.critique


def test_critic_fails_open_on_unparsable_output(monkeypatch):
    """评审判定不可解析时不应卡死流水线：默认放行，但日志要说明原因。"""
    monkeypatch.setattr(real_agents, "chat", lambda **_: "这不是 JSON")
    state = SwarmState(query="q", draft="d")
    real_agents.critic_agent(state)

    assert state.is_approved is True
    assert "评审失败" in state.critique
    assert state.history[-1].agent == "Critic"
