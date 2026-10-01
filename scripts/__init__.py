"""可执行脚本集合（基准、离线演示、冒烟检查）。

作为包存在，是为了让 `python -m scripts.demo_offline` 与 `from scripts import demo_offline`
在类型检查与运行时都只有一种模块名（否则 mypy 会报 source file found twice）。
"""
