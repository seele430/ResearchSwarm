"""调研失败处理测试（步骤 4）。

历史问题：`web_search` 失败时返回字符串 `"搜索失败: ..."`，
`_research_one_task` 把它当搜索结果交给 LLM 提炼 → 等于**让模型基于一句报错编出调研结论**。
现在：失败抛 `SearchError` → 记入 `state.failures`，并作为「信息缺口」传给 Analyst/Writer。
"""

from agents import real_agents
from core.state import SwarmState
from tools import SearchError, SearchResult


def _state(plan: list[str]) -> SwarmState:
    state = SwarmState(query="测试问题")
    state.plan = list(plan)
    return state


def _raise_search_error(*_args, **_kwargs):
    raise SearchError("限流")


def test_search_failure_recorded_and_not_a_finding(monkeypatch):
    monkeypatch.setattr(real_agents, "web_search", _raise_search_error)
    monkeypatch.setattr(real_agents.time, "sleep", lambda *_: None)

    state = _state(["t1"])
    real_agents.researcher_agent(state)

    assert state.findings == {}
    assert "搜索失败" in state.failures["t1"]


def test_error_text_never_leaks_into_findings(monkeypatch):
    monkeypatch.setattr(real_agents, "web_search", _raise_search_error)
    monkeypatch.setattr(real_agents.time, "sleep", lambda *_: None)

    state = _state(["t1", "t2"])
    real_agents.researcher_agent(state)

    assert all("失败" not in text for text in state.findings.values())


def test_retries_once_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(task, max_results=5):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SearchError("限流")
        return [SearchResult(title="标题", url="https://example.com", snippet="摘要")]

    monkeypatch.setattr(real_agents, "web_search", flaky)
    monkeypatch.setattr(real_agents.time, "sleep", lambda *_: None)
    monkeypatch.setattr(real_agents, "chat", lambda **_: "提炼结果")

    state = _state(["t1"])
    real_agents.researcher_agent(state)

    assert calls["n"] == 2, "应当重试一次"
    assert state.findings == {"t1": "提炼结果"}
    assert state.failures == {}


def test_empty_search_result_is_a_failure(monkeypatch):
    monkeypatch.setattr(real_agents, "web_search", lambda *a, **k: [])

    state = _state(["t1"])
    real_agents.researcher_agent(state)

    assert state.findings == {}
    assert state.failures["t1"] == "搜索无结果"


def test_llm_failure_during_digest_is_recorded(monkeypatch):
    monkeypatch.setattr(
        real_agents, "web_search",
        lambda *a, **k: [SearchResult(title="t", url="https://example.com", snippet="s")],
    )

    def boom(**_kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(real_agents, "chat", boom)

    state = _state(["t1"])
    real_agents.researcher_agent(state)

    assert state.findings == {}
    assert "信息提炼失败" in state.failures["t1"]


def test_partial_failure_keeps_successful_findings(monkeypatch):
    def per_task(task, max_results=5):
        if task == "bad":
            raise SearchError("限流")
        return [SearchResult(title="t", url="https://example.com", snippet="s")]

    monkeypatch.setattr(real_agents, "web_search", per_task)
    monkeypatch.setattr(real_agents.time, "sleep", lambda *_: None)
    monkeypatch.setattr(real_agents, "chat", lambda **_: "ok")

    state = _state(["good", "bad"])
    real_agents.researcher_agent(state)

    assert set(state.findings) == {"good"}
    assert set(state.failures) == {"bad"}


def test_analyst_skips_llm_when_nothing_was_found(monkeypatch):
    def must_not_call(**_kwargs):
        raise AssertionError("没有资料时不应调用 LLM")

    monkeypatch.setattr(real_agents, "chat", must_not_call)

    state = SwarmState(query="q")
    state.failures = {"t1": "搜索失败：限流"}
    real_agents.analyst_agent(state)

    assert "无法进行分析" in state.analysis


def test_gap_note_is_injected_into_analyst_prompt(monkeypatch):
    captured = {}

    def fake_chat(system_prompt, user_prompt, temperature=0.7):
        captured["prompt"] = user_prompt
        return "分析结果"

    monkeypatch.setattr(real_agents, "chat", fake_chat)

    state = SwarmState(query="q")
    state.findings = {"t1": "有资料"}
    state.failures = {"t2": "搜索失败：限流"}
    real_agents.analyst_agent(state)

    assert "信息缺口" in captured["prompt"]
    assert "t2" in captured["prompt"]
