"""运行历史（SQLite）与 Markdown 导出的测试。"""

from __future__ import annotations

from typing import Any

from app.export import to_markdown
from core.storage import RunStore

DETAIL: dict[str, Any] = {
    "query": "测试查询",
    "status": "finished",
    "stop_reason": "approved",
    "started_at": "2026-10-01T10:00:00+08:00",
    "finished_at": "2026-10-01T10:00:05+08:00",
    "duration_ms": 5000,
    "approved": True,
    "revision_count": 1,
    "research_rounds": 1,
    "report": "# 报告\n\n结论 [1]",
    "analysis": "分析正文",
    "critique": "合格",
    "plan": ["子任务甲", "子任务乙"],
    "failures": {"任务X": "超时"},
    "sources": [{"title": "来源一", "url": "https://example.com/1"}],
    "usage": {"calls": 9, "total_tokens": 3510, "prompt_tokens": 2700, "completion_tokens": 810},
    "history": [
        {"agent": "Planner", "action": "步骤完成", "at": "2026-10-01T10:00:00+08:00", "duration_ms": 12}
    ],
    "error": "",
}


def test_save_then_get_round_trip(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.save("run1", DETAIL)

    got = store.get("run1")
    assert got is not None
    assert got["query"] == "测试查询"
    assert got["report"].startswith("# 报告")
    assert got["plan"] == ["子任务甲", "子任务乙"]
    assert got["failures"] == {"任务X": "超时"}
    assert got["sources"][0]["url"] == "https://example.com/1"
    assert got["usage"]["calls"] == 9
    assert got["history"][0]["agent"] == "Planner"
    assert got["archived"] is True


def test_save_is_idempotent_and_updates_in_place(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.save("run1", DETAIL)
    store.save("run1", {**DETAIL, "status": "cancelled", "report": "改了"})

    assert store.count() == 1
    updated = store.get("run1")
    assert updated is not None
    assert updated["status"] == "cancelled"
    assert updated["report"] == "改了"


def test_list_is_lightweight_and_newest_first(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.save("old", {**DETAIL, "finished_at": "2026-10-01T09:00:00+08:00"})
    store.save("new", {**DETAIL, "finished_at": "2026-10-01T11:00:00+08:00"})

    rows = store.list()
    assert [row["run_id"] for row in rows] == ["new", "old"]
    assert "report" not in rows[0]  # 列表不带正文
    assert rows[0]["report_chars"] == len(DETAIL["report"])
    assert rows[0]["usage"]["calls"] == 9


def test_get_unknown_run_returns_none(tmp_path):
    assert RunStore(tmp_path / "runs.db").get("does-not-exist") is None


def test_to_markdown_contains_report_sources_and_usage():
    markdown = to_markdown(DETAIL)
    assert markdown.startswith("# 测试查询")
    assert "## 报告" in markdown and "结论 [1]" in markdown
    assert "## 参考来源" in markdown and "[来源一](https://example.com/1)" in markdown
    assert "9 次 / 3510 tokens" in markdown
    assert "## 调研失败项" in markdown and "任务X" in markdown


def test_to_markdown_handles_a_run_without_report():
    markdown = to_markdown({"query": "空跑", "status": "cancelled"})
    assert "# 空跑" in markdown
    assert "（没有产出报告）" in markdown
    assert "## 参考来源" not in markdown
