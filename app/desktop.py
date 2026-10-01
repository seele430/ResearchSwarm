"""桌面窗口入口：pywebview 开一个原生窗口，内部跑 FastAPI（只绑回环地址）。

设计要点
--------
- **单实例**：独占一个锁端口（8755）当互斥量；重复启动直接退出，不会开出一堆窗口。
- **动态端口**：默认 8756，被占用则让系统分配空闲端口；实际端口写入
  `%LOCALAPPDATA%\\ResearchSwarm\\last-run.json`（排查与自动化验证都用它）。
- **零外部依赖**：窗口用系统自带的 WebView2（Windows 11 已预装），不需要装浏览器或 Node。
- **可测试**：GUI 与 webview 都是**懒加载**，所以本模块能在无图形环境的 CI 里被 import 与单测。

开发运行：`python -m app.desktop [--demo]`
打包运行：`run_desktop.py` 被 PyInstaller 打成 `ResearchSwarm.exe`
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

from app.api import DEFAULT_PORT, app, enable_demo_mode

APP_NAME = "ResearchSwarm"
LOCK_PORT = 8755
WINDOW_TITLE = "ResearchSwarm · 多 Agent 深度研究"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
LOG_DIR = DATA_DIR / "logs"


def ensure_std_streams() -> Path | None:
    """`--windowed`（无控制台）下 PyInstaller 会把 sys.stdout/stderr 置为 None。

    此时任何 `print()` 或日志 handler 都会抛异常，直接让整个应用打不开。
    统一把标准流接到 `%LOCALAPPDATA%\\ResearchSwarm\\logs\\desktop.log`：
    既避免崩溃，又让无控制台的桌面版留下可排查的日志。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "desktop.log"
    # 这个流要被 sys.stdout/stderr 长期持有，不能随函数返回就被回收
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return log_path


def find_free_port(preferred: int = DEFAULT_PORT) -> int:
    """优先用 preferred；被占用则让系统分配一个空闲端口。"""
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise RuntimeError("找不到可用端口")


class SingleInstanceLock:
    """用一个只监听回环的套接字当互斥量。

    进程退出（含崩溃）时由操作系统回收端口，所以不会留下"僵尸锁"。
    """

    def __init__(self, port: int = LOCK_PORT) -> None:
        self.port = port
        self._sock: socket.socket | None = None

    def acquire(self) -> bool:
        """拿到锁返回 True；已被其它实例占用返回 False。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", self.port))
            sock.listen(1)
        except OSError:
            sock.close()
            return False
        self._sock = sock
        return True

    def release(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None


def write_runtime_info(port: int, url: str, data_dir: Path | None = None) -> Path:
    """记录本次运行的端口/PID，便于排查与自动化验证。"""
    target_dir = data_dir or DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "last-run.json"
    path.write_text(
        json.dumps(
            {
                "app": APP_NAME,
                "pid": os.getpid(),
                "port": port,
                "url": url,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def start_server_in_thread(host: str, port: int) -> tuple[Any, threading.Thread]:
    """在后台线程里跑 uvicorn。

    主线程必须留给 GUI 事件循环；uvicorn 在非主线程里会自行跳过信号处理。
    """
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    return server, thread


def wait_until_serving(port: int, host: str = "127.0.0.1", timeout: float = 20.0) -> bool:
    """轮询端口，直到内部服务真的开始接受连接。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.2)
    return False


def main() -> int:
    # 必须在任何 print / 日志之前：无控制台模式下没有标准流，先接上日志文件
    log_path = ensure_std_streams()

    parser = argparse.ArgumentParser(description="ResearchSwarm 桌面窗口")
    parser.add_argument("--demo", action="store_true", help="离线演示模式（不调用真实 API）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true", help="打开 webview 调试工具")
    args = parser.parse_args()

    if log_path is not None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] desktop start, log -> {log_path}")

    lock = SingleInstanceLock()
    if not lock.acquire():
        print(f"{APP_NAME} 似乎已经在运行（锁端口 {LOCK_PORT} 被占用），本次启动直接退出。")
        return 1

    try:
        if args.demo:
            enable_demo_mode()

        port = find_free_port(args.port) if args.port == DEFAULT_PORT else args.port
        url = f"http://{args.host}:{port}/"

        server, _thread = start_server_in_thread(args.host, port)
        if not wait_until_serving(port, args.host):
            print("内部服务启动超时，退出。")
            return 2
        write_runtime_info(port, url)
        print(f"{APP_NAME} 内部服务：{url}")

        import webview  # 懒加载：无图形环境（CI）也能 import 本模块

        webview.create_window(
            WINDOW_TITLE,
            url,
            width=1280,
            height=860,
            min_size=(960, 640),
            text_select=True,
        )
        webview.start(debug=args.debug)

        server.should_exit = True
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
