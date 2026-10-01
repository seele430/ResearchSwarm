"""串联 vs 并联调研的可复现测量脚本。

- 默认 `--offline`：用**带固定延迟的桩**替代搜索/LLM，不消耗 API 额度、结果可复现；
- `--live`：真实调用（需要 .env 里的密钥，会消耗 token，且受网络/限流影响）。

用法（项目根目录）：
    python -m scripts.bench_research                     # 离线基准，5 个子任务
    python -m scripts.bench_research --tasks 8 --repeat 3
    python -m scripts.bench_research --live --tasks 5
    python -m scripts.bench_research --out docs/benchmark.md
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from agents import real_agents
from core.state import SwarmState
from tools import SearchResult

SEARCH_LATENCY = 0.8  # 秒，模拟一次搜索往返
LLM_LATENCY = 1.0  # 秒，模拟一次提炼调用
URL_LATENCY = 0.3  # 秒，模拟抓正文（每个子任务抓 RESEARCH_MAX_PAGES 条）


def _install_stubs() -> None:
    """离线桩：延迟固定，因此测的是**调度效率**而不是网络抖动。"""

    def fake_search(task, max_results=5):
        time.sleep(SEARCH_LATENCY)
        return [
            SearchResult(f"{task} 来源{i}", f"https://example.com/{i}", "摘要")
            for i in range(1, min(max_results, 2) + 1)
        ]

    def fake_read(url, max_chars=1200):
        time.sleep(URL_LATENCY)
        return "正文"

    def fake_chat(**kwargs):
        time.sleep(LLM_LATENCY)
        return f"结论：{kwargs.get('user_prompt', '')[:20]}"

    real_agents.web_search = fake_search
    real_agents.read_url = fake_read
    real_agents.chat = fake_chat  # type: ignore[assignment]


def measure(workers: int, tasks: list[str], repeat: int) -> dict:
    """按指定并行度跑 Researcher 阶段，返回中位数耗时。"""
    real_agents.RESEARCH_MAX_WORKERS = workers
    samples = []
    last_state = None

    for _ in range(repeat):
        state = SwarmState(query="benchmark", plan=list(tasks))
        started = time.perf_counter()
        real_agents.researcher_agent(state)
        samples.append(time.perf_counter() - started)
        last_state = state

    assert last_state is not None
    return {
        "workers": workers,
        "seconds": statistics.median(samples),
        "samples": samples,
        "findings": len(last_state.findings),
        "failures": len(last_state.failures),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Researcher 阶段并行度对比")
    parser.add_argument("--tasks", type=int, default=5, help="子任务数量（默认 5）")
    parser.add_argument("--repeat", type=int, default=1, help="每种模式重复次数，取中位数")
    parser.add_argument("--live", action="store_true", help="真实调用 API（默认离线桩）")
    parser.add_argument("--out", type=Path, help="把 Markdown 表格写入文件")
    args = parser.parse_args()

    tasks = [f"子任务 {i}" for i in range(1, args.tasks + 1)]
    if not args.live:
        _install_stubs()

    mode = "真实 API（受网络与限流影响）" if args.live else "离线桩（固定延迟，可复现）"
    serial = measure(1, tasks, args.repeat)
    parallel = measure(5, tasks, args.repeat)

    lines = [
        f"# Researcher 阶段并行度对比（{mode}）",
        "",
        f"- 子任务数：{len(tasks)}　重复次数：{args.repeat}（取中位数）",
        f"- 环境：Python {__import__('platform').python_version()}",
        "",
        "| 模式 | 实现方式 | 耗时 | 加速比 | 成功/失败 |",
        "|------|---------|------|--------|-----------|",
        f"| 串联 | `ThreadPoolExecutor(max_workers=1)` | {serial['seconds']:.2f} s "
        f"| 1.00x | {serial['findings']}/{serial['failures']} |",
        f"| 并联 | `ThreadPoolExecutor(max_workers=5)` | {parallel['seconds']:.2f} s "
        f"| **{serial['seconds'] / parallel['seconds']:.2f}x** "
        f"| {parallel['findings']}/{parallel['failures']} |",
        "",
        "> 生成命令：`python -m scripts.bench_research"
        + (f" --tasks {args.tasks}" if args.tasks != 5 else "")
        + (f" --repeat {args.repeat}" if args.repeat != 1 else "")
        + (" --live" if args.live else "")
        + "`",
    ]
    report = "\n".join(lines)

    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\n已写入 {args.out}")


if __name__ == "__main__":
    main()
