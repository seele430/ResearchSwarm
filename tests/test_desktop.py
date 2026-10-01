"""桌面入口里**可测试**的部分（不启动 GUI 窗口）。

GUI 与 webview 都是懒加载，所以这些测试在无图形环境的 CI 上也能跑。
"""

from __future__ import annotations

import json
import socket

from app import desktop


def test_find_free_port_returns_a_usable_port():
    port = desktop.find_free_port(0)
    assert 1024 <= port <= 65535
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))  # 能绑定 => 确实空闲


def test_find_free_port_falls_back_when_preferred_is_taken():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        taken = sock.getsockname()[1]
        assert desktop.find_free_port(taken) != taken


def test_single_instance_lock_is_exclusive_and_reusable():
    port = desktop.find_free_port(0)
    first = desktop.SingleInstanceLock(port)
    second = desktop.SingleInstanceLock(port)
    try:
        assert first.acquire() is True
        assert second.acquire() is False  # 第二个实例必须被挡掉
    finally:
        first.release()
        second.release()

    third = desktop.SingleInstanceLock(port)
    try:
        assert third.acquire() is True  # 释放后可以重新获取
    finally:
        third.release()


def test_write_runtime_info_records_port_and_pid(tmp_path):
    path = desktop.write_runtime_info(8765, "http://127.0.0.1:8765/", data_dir=tmp_path)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["port"] == 8765
    assert payload["url"].endswith("/")
    assert isinstance(payload["pid"], int)


def test_wait_until_serving_detects_a_listening_socket():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert desktop.wait_until_serving(port, timeout=2) is True


def test_wait_until_serving_times_out_when_nothing_listens():
    port = desktop.find_free_port(0)  # 拿到端口后立即释放，没人监听
    assert desktop.wait_until_serving(port, timeout=1) is False


def test_ensure_std_streams_redirects_to_log_file_when_missing(tmp_path, monkeypatch):
    """windowed 模式下没有控制台（sys.stdout/stderr 为 None），必须能自愈。

    这是打包后「启动即 Unhandled exception」的根因回归测试。
    """
    import sys

    monkeypatch.setattr(desktop, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    log_path = desktop.ensure_std_streams()
    try:
        assert log_path is not None
        assert log_path.exists()
        print("写到日志而不是崩溃")  # 不应抛异常
        sys.stderr.write("stderr 同样可用\n")
    finally:
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "close"):
                stream.close()

    assert "写到日志而不是崩溃" in log_path.read_text(encoding="utf-8")
