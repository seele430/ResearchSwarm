"""ResearchSwarm 命令行入口。"""

import os
from pathlib import Path

from core.orchestrator import run_swarm
from core.state import SwarmState
from core.utils import safe_filename, unique_path

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
    """用 rich 打印执行汇总（requirements 里的 rich 终于派上用场）。"""
    from rich.console import Console
    from rich.table import Table

    table = Table(title="执行汇总")
    table.add_column("步骤")
    table.add_column("耗时", justify="right")
    table.add_column("说明")
    for name, duration, note in build_summary_rows(state):
        table.add_row(name, duration, note)
    Console().print(table)


def main() -> None:
    query = input("请输入你的研究问题：").strip()
    if not query:
        print("问题不能为空")
        return

    state = run_swarm(query, verbose=True)

    # 打印最终报告
    print("=" * 60)
    print("📄 最终报告")
    print("=" * 60)
    print(state.draft)

    # 保存报告到文件（文件名已净化 + 去重）
    report_path = build_report_path(state.query)
    report_path.write_text(state.draft, encoding="utf-8")
    print(f"\n📁 报告已保存到 {report_path}")

    if state.failures:
        print("\n⚠️  以下子任务调研失败，报告可能缺失相应维度：")
        for task, reason in state.failures.items():
            print(f"    - {task}：{reason}")

    # 执行日志（带时间戳与耗时）+ 汇总表
    print("\n" + "=" * 60)
    print("📊 执行日志")
    print("=" * 60)
    for entry in state.history:
        duration = f"  [{entry.duration_ms} ms]" if entry.duration_ms is not None else ""
        print(f"  {entry.at}  [{entry.agent}] {entry.action}{duration}")

    print()
    print_run_summary(state)


if __name__ == "__main__":
    main()
