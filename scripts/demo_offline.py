"""离线演示：不需要 API Key，用假客户端跑**真实流水线**。

替代原 `agents/mock_agents.py` —— 那个 mock 是 Day-1 的平行实现，
内部的 revision 计数语义后来已经改了却没有同步（会漂移）。
这里改为：只替换 LLM 客户端与搜索函数，其余（编排、补研回边、评审循环、
来源汇总、观测）全部走真实代码。

用法（项目根目录）：python -m scripts.demo_offline
"""

from __future__ import annotations

from types import SimpleNamespace

from core import llm, orchestrator
from tools import SearchResult


def _install_fake_llm() -> None:
    """假 LLM 客户端：按 system prompt 分派，并返回带 usage 的响应。"""

    def fake_create(model=None, messages=None, temperature=None):
        system = messages[0]["content"]
        if "信息缺口" in system and "规划专家" in system:
            content = '["补充调研 2026 年最新数据"]'
        elif "规划专家" in system:
            content = '["调研背景", "调研现状"]'
        elif "调研员" in system:
            task = messages[1]["content"].split("子任务：", 1)[1].split("\n", 1)[0].strip()
            content = f"{task} 的结论 [1]"
        elif "研究分析师" in system:
            content = '{"analysis": "分析正文 [1]", "gaps": ["缺少最新数据"]}'
        elif "报告撰写专家" in system:
            content = "# 研究报告\n\n## 结论\n结论基于两轮调研 [1]。"
        elif "质量评审员" in system:
            content = '{"approved": true, "critique": "合格", "score": 9}'
        else:
            content = "?"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=300, completion_tokens=90, total_tokens=390),
        )

    llm._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )


def _install_fake_search() -> None:
    from agents import real_agents

    counter = {"n": 0}

    def fake_search(task, max_results=5):
        counter["n"] += 1
        return [SearchResult(f"{task} 的来源", f"https://example.com/{counter['n']}", "摘要")]

    real_agents.web_search = fake_search
    real_agents.read_url = lambda url, **kwargs: f"{url} 的正文摘录"


def main() -> None:
    from main import build_summary_rows

    _install_fake_llm()
    _install_fake_search()

    state = orchestrator.run_swarm("AI Agent 的发展趋势", verbose=False)

    print(state.draft)
    print("\n最终计划：")
    for task in state.plan:
        print(f"  - {task}")
    print(f"\n补研轮次：{state.research_rounds}（上限 {state.MAX_RESEARCH_ROUNDS}）")

    print("\n执行日志：")
    for entry in state.history:
        duration = f"  [{entry.duration_ms} ms]" if entry.duration_ms is not None else ""
        print(f"  {entry.at}  [{entry.agent}] {entry.action}{duration}")

    print("\n汇总：")
    for name, duration, note in build_summary_rows(state):
        print(f"  {name:<16} {duration:>10}   {note}")


if __name__ == "__main__":
    main()
