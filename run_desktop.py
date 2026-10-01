"""桌面版可执行入口（PyInstaller 的入口脚本）。

开发时也可以用：`python run_desktop.py [--demo]`
之所以单独放一个顶层脚本，是因为 PyInstaller 需要一个完整路径的入口文件，
而 `python -m app.desktop` 的形式在打包后会因为包上下文而报错。
"""

from __future__ import annotations

from app.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
