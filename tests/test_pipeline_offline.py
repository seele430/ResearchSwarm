"""离线端到端测试：替换掉所有外部依赖，跑完整条流水线。

验证的是「编排 + 数据流」是否贯通：
Planner → Researcher(并行+抓正文) → Analyst → Writer ⇄ Critic，
以及来源 URL 是否真的落进了最终报告。
"""

from agents import real_agents
from core import orchestrator
from tools import SearchResult


def test_full_pipeline_offline_produces_sourced_report(monkeypatch):
    def fake_chat(system_prompt, user_prompt, temperature=0.7):
        if "研究任务规划专家" in system_prompt:
            return '["调研背景", "调研现状"]'
        if "调研员" in system_prompt:
            return "子任务结论 [1]"
        if "研究分析师" in system_prompt:
            return '{"analysis": "综合分析 [1]", "gaps": []}'
        if "报告撰写专家" in system_prompt:
            return "# 研究报告\n\n## 结论\n行业共识大于分歧 [1]。"
        if "质量评审员" in system_prompt:
            return '{"approved": true, "critique": "合格", "score": 9}'
        raise AssertionError(f"未预期的 system prompt: {system_prompt[:40]}")

    counter = {"n": 0}

    def fake_search(task, max_results=5):
        counter["n"] += 1
        return [
            SearchResult(
                title=f"{task} 的来源",
                url=f"https://example.com/{counter['n']}",
                snippet="摘要",
            )
        ]

    monkeypatch.setattr(real_agents, "chat", fake_chat)
    monkeypatch.setattr(real_agents, "web_search", fake_search)
    monkeypatch.setattr(real_agents, "read_url", lambda url, **kwargs: f"{url} 的正文内容")

    state = orchestrator.run_swarm("AI Agent 的发展趋势", verbose=False)

    # 流水线跑通
    assert state.plan == ["调研背景", "调研现状"]
    assert set(state.findings) == {"调研背景", "调研现状"}
    assert state.failures == {}
    assert state.is_approved is True
    assert state.revision_count == 0

    # 五个角色都留下了日志
    assert {h.agent for h in state.history} == {
        "Planner", "Researcher", "Analyst", "Writer", "Critic"
    }

    # 关键：报告里有可核验的真实来源
    assert "## 参考来源" in state.draft
    assert "https://example.com/1" in state.draft
    assert "https://example.com/2" in state.draft
    assert len(state.sources) == 2
