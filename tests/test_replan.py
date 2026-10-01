"""补研回边测试（步骤 8）。

历史状态：Planner → Researcher → Analyst → Writer ⇄ Critic 是一条**固定流水线**，
Analyst 发现的"信息缺口"没有任何去处，也没有重新调研的能力 —— 严格说那叫
prompt chaining，不叫多 Agent 协作。

现在：Analyst 报出缺口 → Planner 据此追加子任务 → Researcher 再调研一轮 →
Analyst 复评（最多 MAX_RESEARCH_ROUNDS 轮），调研失败的任务也会在同一轮里重试。
"""

from agents import real_agents
from core import orchestrator
from core.state import SwarmState
from tools import SearchResult


def _install_loop_fakes(monkeypatch, calls, *, gaps_per_round, fail_first_round=False,
                        new_task_name="补研任务"):
    """编排层假实现：只验证回边的调度与状态流转。"""

    def planner(state: SwarmState):
        state.plan = ["任务1"]

    def researcher(state: SwarmState, tasks=None):
        targets = list(tasks) if tasks else list(state.plan)
        calls["researcher"].append(targets)
        for task in targets:
            if fail_first_round and len(calls["researcher"]) == 1:
                state.failures[task] = "限流"
                continue
            state.findings[task] = f"{task} 的结果"
            state.failures.pop(task, None)

    def analyst(state: SwarmState):
        calls["analyst"] += 1
        state.analysis = "分析正文"
        state.gaps = list(gaps_per_round)

    def planner_extend(state: SwarmState):
        if not state.gaps:
            return  # 与真实实现一致：没有缺口就什么也不做
        calls["extend"] += 1
        state.plan.append(f"{new_task_name}{calls['extend']}")
        state.gaps = []

    def writer(state: SwarmState):
        state.draft = "报告"

    def critic(state: SwarmState):
        state.is_approved = True

    monkeypatch.setattr(orchestrator, "planner_agent", planner)
    monkeypatch.setattr(orchestrator, "researcher_agent", researcher)
    monkeypatch.setattr(orchestrator, "analyst_agent", analyst)
    monkeypatch.setattr(orchestrator, "planner_extend_agent", planner_extend)
    monkeypatch.setattr(orchestrator, "writer_agent", writer)
    monkeypatch.setattr(orchestrator, "critic_agent", critic)


def test_no_gaps_means_no_extra_round(monkeypatch):
    calls = {"researcher": [], "analyst": 0, "extend": 0}
    _install_loop_fakes(monkeypatch, calls, gaps_per_round=[])

    state = orchestrator.run_swarm("q", verbose=False)

    assert calls["extend"] == 0
    assert calls["researcher"] == [["任务1"]]
    assert calls["analyst"] == 1
    assert state.research_rounds == 0


def test_gaps_trigger_one_supplementary_round(monkeypatch):
    calls = {"researcher": [], "analyst": 0, "extend": 0}
    _install_loop_fakes(monkeypatch, calls, gaps_per_round=["缺 A 的最新数据"])

    state = orchestrator.run_swarm("q", verbose=False)

    assert calls["extend"] == 1, "缺口应触发一次补研规划"
    assert calls["researcher"] == [["任务1"], ["补研任务1"]], "第二轮只调研新增子任务"
    assert calls["analyst"] == 2, "补研后应复评一次"
    assert state.research_rounds == 1


def test_rounds_are_capped(monkeypatch):
    calls = {"researcher": [], "analyst": 0, "extend": 0}
    # Analyst 每轮都报缺口，Planner 每轮都加新任务 —— 仍然只补一轮
    _install_loop_fakes(monkeypatch, calls, gaps_per_round=["永远缺"])

    state = orchestrator.run_swarm("q", verbose=False)

    assert state.research_rounds == SwarmState.MAX_RESEARCH_ROUNDS == 1
    assert calls["extend"] == 1
    assert calls["analyst"] == 2


def test_failed_task_is_retried_and_failure_cleared(monkeypatch):
    calls = {"researcher": [], "analyst": 0, "extend": 0}
    _install_loop_fakes(monkeypatch, calls, gaps_per_round=[], fail_first_round=True)

    state = orchestrator.run_swarm("q", verbose=False)

    assert calls["researcher"] == [["任务1"], ["任务1"]], "失败项应在补研轮重试"
    assert state.failures == {}, "重试成功后失败记录要撤销"
    assert state.findings == {"任务1": "任务1 的结果"}
    assert state.research_rounds == 1


def test_gap_and_failure_share_one_round(monkeypatch):
    calls: dict = {"researcher": [], "analyst": 0, "extend": 0}
    _install_loop_fakes(
        monkeypatch, calls, gaps_per_round=["缺 A"], fail_first_round=True
    )

    state = orchestrator.run_swarm("q", verbose=False)

    # 一轮里同时处理：新增子任务 + 失败重试
    assert calls["researcher"][1] == ["补研任务1", "任务1"]
    assert state.research_rounds == 1


# ---------- 回边两端的 Agent 行为 ----------


def test_analyst_records_gaps_from_json(monkeypatch):
    monkeypatch.setattr(
        real_agents, "chat",
        lambda **_: '{"analysis": "分析正文", "gaps": ["缺 A", "缺 B", "  ", 3]}',
    )
    state = SwarmState(query="q", findings={"t1": "资料"})
    real_agents.analyst_agent(state)

    assert state.analysis == "分析正文"
    assert state.gaps == ["缺 A", "缺 B"], "空串与非字符串项应被过滤"


def test_analyst_falls_back_when_model_returns_markdown(monkeypatch):
    monkeypatch.setattr(real_agents, "chat", lambda **_: "## 分析\n- 要点一")
    state = SwarmState(query="q", findings={"t1": "资料"})
    real_agents.analyst_agent(state)

    assert "要点一" in state.analysis, "分析正文不能因为格式问题丢掉"
    assert state.gaps == []


def test_planner_extend_adds_tasks_and_clears_gaps(monkeypatch):
    monkeypatch.setattr(real_agents, "chat", lambda **_: '["补充调研 A 的数据"]')
    state = SwarmState(query="q", plan=["已有任务"], gaps=["缺 A"])

    real_agents.planner_extend_agent(state)

    assert state.plan == ["已有任务", "补充调研 A 的数据"]
    assert state.gaps == [], "缺口被消费后要清空，避免回边空转"


def test_planner_extend_falls_back_to_gap_text(monkeypatch):
    monkeypatch.setattr(real_agents, "chat", lambda **_: "抱歉，我无法输出 JSON")
    state = SwarmState(query="q", plan=["已有任务"], gaps=["缺 A"])

    real_agents.planner_extend_agent(state)

    assert state.plan == ["已有任务", "补充调研：缺 A"]


def test_planner_extend_falls_back_when_all_tasks_duplicate(monkeypatch):
    monkeypatch.setattr(real_agents, "chat", lambda **_: '["已有任务"]')
    state = SwarmState(query="q", plan=["已有任务"], gaps=["缺 A"])

    real_agents.planner_extend_agent(state)

    assert state.plan == ["已有任务", "补充调研：缺 A"]


def test_planner_extend_is_noop_without_gaps(monkeypatch):
    def must_not_call(**_kwargs):
        raise AssertionError("没有缺口时不应调用 LLM")

    monkeypatch.setattr(real_agents, "chat", must_not_call)
    state = SwarmState(query="q", plan=["已有任务"])

    real_agents.planner_extend_agent(state)

    assert state.plan == ["已有任务"]


def test_researcher_can_target_specific_tasks(monkeypatch):
    seen = []

    def fake_search(task, max_results=5):
        seen.append(task)
        return [SearchResult(f"{task} 来源", f"https://example.com/{task}", "摘要")]

    monkeypatch.setattr(real_agents, "web_search", fake_search)
    monkeypatch.setattr(real_agents, "read_url", lambda url, **k: "正文")
    monkeypatch.setattr(real_agents, "chat", lambda **_: "结论")

    state = SwarmState(query="q", plan=["旧任务", "新任务"])
    real_agents.researcher_agent(state, tasks=["新任务"])

    assert seen == ["新任务"], "指定 tasks 时不应再跑全量计划"
    assert set(state.findings) == {"新任务"}
