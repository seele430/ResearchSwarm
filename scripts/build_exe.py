"""用 PyInstaller 打出可双击运行的 ResearchSwarm.exe。

用法（项目根目录）：

    venv\\Scripts\\python.exe scripts\\build_exe.py

产物：`dist/ResearchSwarm/ResearchSwarm.exe`

为什么用 onedir 而不是 onefile：
- 启动快（onefile 每次运行都要解压到临时目录）；
- 杀软误报少（onefile 的自解压行为常被启发式拦截）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "run_desktop.py"
ICON = ROOT / "assets" / "icon.ico"
DIST = ROOT / "dist"
NAME = "ResearchSwarm"

# uvicorn / fastapi 大量使用运行时动态导入，必须显式告知 PyInstaller
HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "webview.platforms.edgechromium",
]


def build(console: bool = False, name: str = NAME) -> int:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        name,
        # 桌面程序用 --windowed（不弹控制台）；排查启动异常时用 --console 才看得到栈
        "--console" if console else "--windowed",
    ]
    if ICON.exists():
        args += ["--icon", str(ICON)]
    args += [
        "--add-data",
        f"web{os.pathsep}web",  # 静态前端必须一起打包
        "--collect-data",
        "trafilatura",  # trafilatura 自带数据文件，漏了会在抓正文时报错
        "--collect-all",
        "webview",  # pywebview 自带 WebView2 的 .NET DLL，必须整体带上
        *[f"--hidden-import={name}" for name in HIDDEN_IMPORTS],
        str(ENTRY),
    ]

    print("$ " + " ".join(args))
    result = subprocess.run(args, cwd=ROOT, check=False)
    if result.returncode == 0:
        exe = DIST / name / f"{name}.exe"
        print(f"构建完成：{exe}（存在: {exe.exists()}）")
    else:
        print(f"构建失败，退出码 {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    is_console = "--console" in sys.argv
    raise SystemExit(build(console=is_console, name=f"{NAME}Debug" if is_console else NAME))
