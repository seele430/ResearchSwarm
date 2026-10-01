"""命令行前端：订阅运行事件并渲染成终端输出，同时负责保存报告与打印汇总。

这是「core 不 print」之后 CLI 的归宿：**同一套事件**，CLI 渲染成文字，
M2 的 FastAPI 会把它序列化成 SSE 推给浏览器。
"""

from __future__ import annotations

import os
from pathlib import Path

from core.orchestrator import run_swarm
from core.state import SwarmState
from core.utils import safe_filename, unique_path
from service.events import RunEvent

NOTES_DIR = "notes"
REPORT_STEM_MAX = 40


def build_report_path(query: str, directory: str = NOTES_DIR) -> Path:
    """把用户问题变成「安全 + 不重名」的报告路径。

    历史问题：直接用 `query[:20]` 拼文件名，问句里带 `:` `?` `*` `/` 会崩，
    前 20 字相同还会互相覆盖。
    """
    os.makedirs(directory, exist_ok=True)
    stem = safe_filename(query, max_length=REPORT_STEM_MAX, fallback="report")
    return unique_path(Path(directory) / f"report_{stem}.md")


def build_summary_rows(state: SwarmState) -> list[tuple[str, str, str]]:
    """汇总「步骤 / 耗时 / 说明」三列。纯函数，便于测试。"""
    rows: list[tuple[str, str, str]] = []
    for entry in state.history:
        if entry.duration_ms is None:
            continue
        rows.append((entry.agent, f"{entry.duration_ms / 1000:.1f}s", entry.action))

    usage = state.usage
    rows.append(
        (
            "LLM 用量",
            f"{usage.calls} 次调用",
            f"prompt {usage.prompt_tokens} + completion {usage.completion_tokens}"
            f" = {usage.total_tokens} tokens",
        )
    )
    rows.append(("总耗时", f"{state.duration_ms / 1000:.1f}s", f"开始于 {state.started_at}"))
    return rows


def print_run_summary(state: SwarmState) -> None:
    """用 rich 打印执行汇总。"""
    from rich.console import Console
    from rich.table import Table

    table = Table(title="执行汇总")
    table.add_column("步骤")
    table.add_column("耗时", justify="right")
    table.add_column("说明")
    for name, duration, note in build_summary_rows(state):
        table.add_row(name, duration, note)
    Console().print(table)


def render_event(event: RunEvent) -> None:
    """把一条事件渲染成终端文字（与重构前的输出保持一致）。"""
    if event.type == "run_started":
        print(f"\n{'=' * 60}")
        print("🚀 ResearchSwarm 启动")
        print(f"📝 用户问题：{event.data.get('query', '')}")
        print(f"{'=' * 60}\n")

    elif event.type == "step_started":
        print(f"▶️  [{event.agent}] 执行中...")

    elif event.type == "step_finished":
        ms = event.duration_ms or 0
        print(f"   ⏱  [{event.agent}] {ms / 1000:.1f}s")

    elif event.type == "round_started":
        gaps = len(event.data.get("gaps", []))
        failures = len(event.data.get("failures", []))
        print(f"🔁 第 {event.data.get('round')} 轮补充调研（缺口 {gaps} / 失败 {failures}）\n")

    elif event.type == "round_skipped":
        print("   （没有可补研的子任务，结束回边）\n")

    elif event.type == "rewrite_started":
        print(
            f"🔄 打回重写（第 {event.data.get('revision')}/{event.data.get('max_revisions')} 次）\n"
        )

    elif event.type == "run_cancelled":
        print(f"\n⏹  已取消（阶段：{event.data.get('stage')}）—— 已完成的步骤保留\n")

    elif event.type == "run_finished":
        reason = event.data.get("stop_reason")
        if reason == "approved":
            print("✅ Critic 通过，任务结束\n")
        elif reason == "max_revisions":
            print(f"⚠️  已达到最大重写次数 {event.data.get('revision_count')}，强制结束\n")


def run_cli(query: str) -> SwarmState:
    """跑一次完整流程：渲染进度 → 打印报告 → 保存文件 → 打印日志与汇总。"""
    state = run_swarm(query, on_event=render_event)

    print("=" * 60)
    print("📄 最终报告")
    print("=" * 60)
    print(state.draft)

    if state.draft:
        report_path = build_report_path(state.query)
        report_path.write_text(state.draft, encoding="utf-8")
        print(f"\n📁 报告已保存到 {report_path}")

    if state.failures:
        print("\n⚠️  以下子任务调研失败，报告可能缺失相应维度：")
        for task, reason in state.failures.items():
            print(f"    - {task}：{reason}")

    print("\n" + "=" * 60)
    print("📊 执行日志")
    print("=" * 60)
    for entry in state.history:
        duration = f"  [{entry.duration_ms} ms]" if entry.duration_ms is not None else ""
        print(f"  {entry.at}  [{entry.agent}] {entry.action}{duration}")

    print()
    print_run_summary(state)
    return state
