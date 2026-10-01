"""把一次运行导出成 Markdown（纯函数，便于单测）。

导出内容 = 头部元信息 + 报告正文 + 附加的来源清单。
元信息用引用块，方便直接粘进笔记/issue。
"""

from __future__ import annotations

from typing import Any


def _fmt_seconds(ms: Any) -> str:
    try:
        return f"{int(ms or 0) / 1000:.1f}s"
    except (TypeError, ValueError):
        return "?"


def to_markdown(detail: dict[str, Any]) -> str:
    """`detail` 的形状与 `GET /api/runs/{run_id}` 一致。"""
    usage = detail.get("usage") or {}
    sources = detail.get("sources") or []
    failures = detail.get("failures") or {}

    lines: list[str] = [f"# {detail.get('query', '（无标题）')}", ""]

    meta = [
        f"状态 `{detail.get('status', '?')}`",
        f"结束原因 `{detail.get('stop_reason') or '-'}`",
        f"耗时 {_fmt_seconds(detail.get('duration_ms'))}",
        f"LLM {usage.get('calls', 0)} 次 / {usage.get('total_tokens', 0)} tokens",
        f"计划 {len(detail.get('plan') or [])} 项",
        f"补研 {detail.get('research_rounds', 0)} 轮",
        f"评审重写 {detail.get('revision_count', 0)} 次",
    ]
    if detail.get("finished_at"):
        meta.append(f"于 {detail['finished_at']}")
    lines += ["> 由 ResearchSwarm 生成 · " + " · ".join(meta), ""]

    lines += ["## 报告", "", (detail.get("report") or "（没有产出报告）").strip(), ""]

    if failures:
        lines += ["## 调研失败项", ""]
        lines += [f"- **{task}**：{reason}" for task, reason in failures.items()]
        lines += [""]

    if sources:
        lines += ["## 参考来源", ""]
        for index, src in enumerate(sources, start=1):
            title = src.get("title") or src.get("url") or "来源"
            lines.append(f"{index}. [{title}]({src.get('url', '')})")
        lines += [""]

    return "\n".join(lines).rstrip() + "\n"
