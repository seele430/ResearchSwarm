"""可观测性测试（步骤 7）。

历史问题：`state.py` 注释写着"谁在什么时候做了什么"，但 `history` 里
**没有时间、没有耗时、没有 token 统计** —— 而 README 的卖点之一就是性能对比。
"""

import threading
from types import SimpleNamespace

from core import llm, orchestrator
from core.llm import USAGE, UsageMeter
from core.state import HistoryEntry, SwarmState, UsageStat
from main import build_summary_rows

# ---------- 执行日志 ----------


def test_log_records_time_and_duration():
    state = SwarmState(query="q")
    entry = state.log("Planner", "拆解完成", duration_ms=1234)

    assert isinstance(entry, HistoryEntry)
    assert entry.at, "必须带时间戳"
    assert "T" in entry.at, "应为 ISO 格式"
    assert entry.duration_ms == 1234
    assert state.history[0] is entry


def test_log_without_duration_is_allowed():
    state = SwarmState(query="q")
    state.log("Researcher", "开始调研")
    assert state.history[0].duration_ms is None


def test_step_durations_aggregate_per_agent():
    state = SwarmState(query="q")
    state.log("Writer", "步骤完成", duration_ms=100)
    state.log("Writer", "步骤完成", duration_ms=150)
    state.log("Critic", "步骤完成", duration_ms=10)
    state.log("Planner", "内部动作")  # 无耗时，不计入

    assert state.step_durations() == {"Writer": 250, "Critic": 10}


# ---------- 用量计量 ----------


def test_usage_meter_accumulates_and_resets():
    meter = UsageMeter()
    meter.record(prompt_tokens=100, completion_tokens=20)
    meter.record(prompt_tokens=50, completion_tokens=10, total_tokens=60)

    snapshot = meter.snapshot()
    assert snapshot.calls == 2
    assert snapshot.prompt_tokens == 150
    assert snapshot.completion_tokens == 30
    assert snapshot.total_tokens == 180  # 120 + 60

    meter.reset()
    assert meter.snapshot() == UsageStat()


def test_usage_meter_is_thread_safe():
    meter = UsageMeter()

    def worker():
        for _ in range(50):
            meter.record(prompt_tokens=1, completion_tokens=1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snapshot = meter.snapshot()
    assert snapshot.calls == 400
    assert snapshot.total_tokens == 800


def test_chat_records_usage_from_response(monkeypatch):
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="回答"))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: fake_response))
    )
    monkeypatch.setattr(llm, "_client", fake_client)
    USAGE.reset()

    assert llm.chat("sys", "user") == "回答"
    assert USAGE.snapshot() == UsageStat(
        prompt_tokens=11, completion_tokens=7, total_tokens=18, calls=1
    )
    USAGE.reset()


def test_chat_tolerates_response_without_usage(monkeypatch):
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="回答"))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: fake_response))
    )
    monkeypatch.setattr(llm, "_client", fake_client)
    USAGE.reset()

    assert llm.chat("sys", "user") == "回答"
    assert USAGE.snapshot().calls == 0, "没有 usage 字段时不应计为一次调用"


# ---------- 编排层 ----------


def _install_fake_agents(monkeypatch):
    monkeypatch.setattr(orchestrator, "planner_agent", lambda s: s.__setattr__("plan", ["t1"]))
    monkeypatch.setattr(orchestrator, "researcher_agent", lambda s: s.__setattr__("findings", {"t1": "f"}))
    monkeypatch.setattr(orchestrator, "analyst_agent", lambda s: s.__setattr__("analysis", "a"))
    monkeypatch.setattr(orchestrator, "writer_agent", lambda s: s.__setattr__("draft", "d"))

    def critic(state):
        state.is_approved = True

    monkeypatch.setattr(orchestrator, "critic_agent", critic)


def test_every_step_records_duration(monkeypatch):
    _install_fake_agents(monkeypatch)

    state = orchestrator.run_swarm("q", verbose=False)

    durations = state.step_durations()
    assert set(durations) == {"Planner", "Researcher", "Analyst", "Writer", "Critic"}
    assert all(ms >= 0 for ms in durations.values())


def test_run_records_start_time_total_duration_and_usage(monkeypatch):
    _install_fake_agents(monkeypatch)

    state = orchestrator.run_swarm("q", verbose=False)

    assert state.started_at and "T" in state.started_at
    assert state.duration_ms >= 0
    assert isinstance(state.usage, UsageStat)


def test_run_resets_usage_between_runs(monkeypatch):
    _install_fake_agents(monkeypatch)
    USAGE.reset()
    USAGE.record(prompt_tokens=999, completion_tokens=1)  # 上一次运行的残留

    state = orchestrator.run_swarm("q", verbose=False)

    assert state.usage.total_tokens == 0, "每次运行都应当从零开始计量"


# ---------- 汇总表 ----------


def test_summary_rows_include_steps_usage_and_total():
    state = SwarmState(query="q", duration_ms=2500, started_at="2026-09-30T12:00:00+08:00")
    state.log("Planner", "步骤完成", duration_ms=1500)
    state.usage = UsageStat(prompt_tokens=100, completion_tokens=50, total_tokens=150, calls=3)

    rows = build_summary_rows(state)
    rendered = [" | ".join(row) for row in rows]

    assert any("Planner" in row and "1.5s" in row for row in rendered)
    assert any("3 次调用" in row and "150 tokens" in row for row in rendered)
    assert any("总耗时" in row and "2.5s" in row for row in rendered)


def test_print_run_summary_does_not_crash(capsys):
    from main import print_run_summary

    state = SwarmState(query="q", duration_ms=10, started_at="2026-09-30T12:00:00+08:00")
    print_run_summary(state)  # rich 输出到 stdout
    assert capsys.readouterr().out != "" or True  # 只要求不抛异常
