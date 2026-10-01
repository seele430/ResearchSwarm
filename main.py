"""ResearchSwarm 命令行入口（薄壳）。

界面逻辑已搬到 `app/cli.py`；这里保留同名再导出，因为既有测试与
`scripts/demo_offline.py` 会 `from main import build_report_path / build_summary_rows /
print_run_summary`。新增界面（FastAPI、桌面窗口）不经过本文件。
"""

from app.cli import (
    NOTES_DIR,
    REPORT_STEM_MAX,
    build_report_path,
    build_summary_rows,
    print_run_summary,
    run_cli,
)

__all__ = [
    "NOTES_DIR",
    "REPORT_STEM_MAX",
    "build_report_path",
    "build_summary_rows",
    "main",
    "print_run_summary",
    "run_cli",
]


def main() -> None:
    query = input("请输入你的研究问题：").strip()
    if not query:
        print("问题不能为空")
        return
    run_cli(query)


if __name__ == "__main__":
    main()
