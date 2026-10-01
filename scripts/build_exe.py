"""用 PyInstaller 打出可双击运行的 ResearchSwarm.exe。

用法（项目根目录）：

    venv\\Scripts\\python.exe scripts\\build_exe.py             # 目录版（自己日常用，推荐）
    venv\\Scripts\\python.exe scripts\\build_exe.py --onefile   # 单文件版（发给别人最省事）
    venv\\Scripts\\python.exe scripts\\build_exe.py --console   # 控制台调试版（排查启动异常）

产物：
- 目录版：`dist/ResearchSwarm/ResearchSwarm.exe`（+ `_internal/`，**必须整目录分发**）
- 单文件版：`dist/single/ResearchSwarm.exe`（一个文件即可分发）

两种形态的取舍：
- onedir（默认）：启动快（实测约 3.6 秒）、杀软误报少；代价是 2600+ 个文件必须整目录发
- onefile：只发一个文件；代价是每次启动都要自解压到 %TEMP%\\_MEIxxxx，冷启动约 9-10 秒，
  且自解压行为偶尔被启发式拦截

两种形态共用同一份代码：静态资源通过 `sys._MEIPASS` 定位（见 `app/api.py`），
所以 `--add-data web;web` 在两种形态下都有效。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "run_desktop.py"
ICON = ROOT / "assets" / "icon.ico"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
NAME = "ResearchSwarm"

# 随包一起分发的文档：接收方解压后第一眼就能看到「怎么用、去哪申请 API Key」
BUNDLED_DOCS = [ROOT / "使用说明.txt", ROOT / "README.md"]

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


def copy_docs(target_dir: Path) -> list[Path]:
    """把使用说明与 README 复制到发布目录（接收方解压即可见）。"""
    if not target_dir.is_dir():
        return []
    copied: list[Path] = []
    for src in BUNDLED_DOCS:
        if src.exists():
            dest = target_dir / src.name
            shutil.copy2(src, dest)
            copied.append(dest)
    return copied


def build(console: bool = False, onefile: bool = False, name: str = NAME) -> int:
    """跑一次 PyInstaller；返回退出码（0 表示成功）。"""
    # 两种形态各自独立的输出/中间目录，互不覆盖，方便共存
    dist_dir = (DIST / "single") if onefile else (DIST / name)
    work_dir = BUILD / ("single" if onefile else "onedir")
    work_dir.mkdir(parents=True, exist_ok=True)

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
        "--onefile" if onefile else "--onedir",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(work_dir),
    ]
    if ICON.exists():
        args += ["--icon", str(ICON)]
    args += [
        "--add-data",
        # 用绝对路径：一旦指定 --specpath，PyInstaller 会按 spec 所在目录解析相对路径
        f"{ROOT / 'web'}{os.pathsep}web",  # 静态前端必须一起打包
        "--collect-data",
        "trafilatura",  # trafilatura 自带数据文件，漏了会在抓正文时报错
        "--collect-all",
        "webview",  # pywebview 自带 WebView2 的 .NET DLL，必须整体带上
        *[f"--hidden-import={item}" for item in HIDDEN_IMPORTS],
        str(ENTRY),
    ]

    print("$ " + " ".join(args))
    result = subprocess.run(args, cwd=ROOT, check=False)
    if result.returncode != 0:
        print(f"构建失败，退出码 {result.returncode}")
        return result.returncode

    exe = dist_dir / f"{name}.exe"
    size_mb = exe.stat().st_size / 1024 / 1024 if exe.exists() else 0.0
    print(f"构建完成（{'onefile' if onefile else 'onedir'}）：{exe}  {size_mb:.1f} MB")
    for doc in copy_docs(dist_dir):
        print(f"  随包文档：{doc.name}")
    return 0


if __name__ == "__main__":
    is_console = "--console" in sys.argv
    is_onefile = "--onefile" in sys.argv
    raise SystemExit(
        build(
            console=is_console,
            onefile=is_onefile,
            name=f"{NAME}Debug" if is_console else NAME,
        )
    )
