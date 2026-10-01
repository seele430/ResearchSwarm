"""来源（引用）链路测试（步骤 5）。

背景：README 号称"真实联网、深度研究"，但示例报告与 `notes/` 里的报告
**http 链接数为 0** —— 结论无一可核验。
现在：Researcher 抓取正文 → 来源入 `state.sources` → Writer 报告末尾附确定性来源清单。
"""

from agents import real_agents
from core.state import SourceRef, SwarmState
from tools import FetchError, SearchError, SearchResult


def _results(*urls: str) -> list[SearchResult]:
    return [
        SearchResult(title=f"标题{i}", url=url, snippet=f"摘要{i}")
        for i, url in enumerate(urls, 1)
    ]


def _state(plan: list[str], **kwargs) -> SwarmState:
    state = SwarmState(query="测试问题", **kwargs)
    state.plan = list(plan)
    return state


def test_researcher_fetches_pages_and_records_sources(monkeypatch):
    captured = {}

    def fake_chat(system_prompt, user_prompt, temperature=0.7):
        captured["prompt"] = user_prompt
        return "结论内容"

    monkeypatch.setattr(
        real_agents, "web_search",
        lambda *a, **k: _results("https://a.example", "https://b.example"),
    )
    monkeypatch.setattr(real_agents, "read_url", lambda url, **k: f"{url} 的正文内容")
    monkeypatch.setattr(real_agents, "chat", fake_chat)

    state = _state(["t1"])
    real_agents.researcher_agent(state)

    # 正文被抓进 prompt（不再只有 300 字摘要）
    assert "https://a.example 的正文内容" in captured["prompt"]
    # 来源入账，且 URL 真实来自搜索
    assert [s.url for s in state.sources] == ["https://a.example", "https://b.example"]
    assert all(isinstance(s, SourceRef) for s in state.sources)
    assert state.sources[0].task == "t1"


def test_page_fetch_failure_degrades_to_snippet(monkeypatch):
    captured = {}

    def boom(url, **kwargs):
        raise FetchError("403")

    monkeypatch.setattr(real_agents, "web_search", lambda *a, **k: _results("https://a.example"))
    monkeypatch.setattr(real_agents, "read_url", boom)

    def fake_chat(system_prompt, user_prompt, temperature=0.7):
        captured["p"] = user_prompt
        return "结论"

    monkeypatch.setattr(real_agents, "chat", fake_chat)

    state = _state(["t1"])
    real_agents.researcher_agent(state)

    # 正文抓取失败不影响任务完成，但要退化到摘要并如实标注
    assert state.findings == {"t1": "结论"}
    assert state.failures == {}
    assert "摘要1" in captured["p"]
    assert "正文抓取失败" in captured["p"]
    assert [s.url for s in state.sources] == ["https://a.example"]


def test_sources_are_deduplicated_across_tasks(monkeypatch):
    monkeypatch.setattr(
        real_agents, "web_search",
        lambda *a, **k: _results("https://same.example", "https://other.example"),
    )
    monkeypatch.setattr(real_agents, "read_url", lambda url, **k: "正文")
    monkeypatch.setattr(real_agents, "chat", lambda **_: "结论")

    state = _state(["t1", "t2"])
    real_agents.researcher_agent(state)

    urls = [s.url for s in state.sources]
    assert urls == ["https://same.example", "https://other.example"], "重复 URL 只应记录一次"
    assert state.sources[0].task == "t1", "保留首次出现的归属"


def test_search_failure_records_no_sources(monkeypatch):
    def boom(*_a, **_k):
        raise SearchError("限流")

    monkeypatch.setattr(real_agents, "web_search", boom)
    monkeypatch.setattr(real_agents.time, "sleep", lambda *_: None)

    state = _state(["t1"])
    real_agents.researcher_agent(state)

    assert state.sources == []
    assert "搜索失败" in state.failures["t1"]


def test_writer_appends_source_appendix_when_missing(monkeypatch):
    monkeypatch.setattr(real_agents, "chat", lambda **_: "# 报告\n\n## 结论\n一切向好。")

    state = SwarmState(query="q", analysis="分析")
    state.sources = [
        SourceRef(title="来源甲", url="https://a.example", task="t1"),
        SourceRef(title="来源乙", url="https://b.example", task="t2"),
    ]
    real_agents.writer_agent(state)

    assert "## 参考来源" in state.draft
    assert "https://a.example" in state.draft
    assert "https://b.example" in state.draft
    assert "来源甲" in state.draft


def test_writer_does_not_duplicate_existing_source_section(monkeypatch):
    draft = "# 报告\n\n## 参考来源\n- [1] 来源甲 https://a.example\n"
    monkeypatch.setattr(real_agents, "chat", lambda **_: draft)

    state = SwarmState(query="q", analysis="分析")
    state.sources = [SourceRef(title="来源甲", url="https://a.example", task="t1")]
    real_agents.writer_agent(state)

    assert state.draft.count("## 参考来源") == 1
    assert state.draft == draft


def test_writer_without_sources_stays_untouched(monkeypatch):
    monkeypatch.setattr(real_agents, "chat", lambda **_: "# 报告\n无来源")
    state = SwarmState(query="q", analysis="分析")
    real_agents.writer_agent(state)

    assert state.draft == "# 报告\n无来源"
    assert "参考来源" not in state.draft


def test_analyst_prompt_carries_source_list(monkeypatch):
    captured = {}

    def fake_chat(system_prompt, user_prompt, temperature=0.7):
        captured["prompt"] = user_prompt
        return "分析"

    monkeypatch.setattr(real_agents, "chat", fake_chat)

    state = SwarmState(query="q", findings={"t1": "资料"})
    state.sources = [SourceRef(title="来源甲", url="https://a.example", task="t1")]
    real_agents.analyst_agent(state)

    assert "https://a.example" in captured["prompt"]
    assert "参考来源" in captured["prompt"]
