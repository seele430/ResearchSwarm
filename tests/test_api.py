"""FastAPI 后端（HTTP + SSE）的离线测试。

覆盖 M2 的验收点：
- 静态前端与 /api/* 的挂载顺序正确（互不遮挡）
- 一次运行能通过 SSE 收到完整事件流，并在结束后取到报告 / 来源 / 用量
- 取消接口能在步骤边界把运行停下（不执行 Writer）
- 同一时刻只允许一个运行（进程级计量器的现实约束）→ 409
- 未知 run_id → 404

所有测试都用离线桩，绝不真的调用 LLM 或搜索。
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents import real_agents
from app import api


def _install_stubs(monkeypatch, *, delay: float = 0.0) -> None:
    """复用 scripts.demo_offline 的桩。

    关键：替换的是 `core.llm._client`（而不是 `real_agents.chat`），
    这样**真实的 core.llm.chat 仍然执行**，token 计量器才会累加 ——
    与 `python -m app.api --demo` 走的是同一条路径。

    monkeypatch 先记下原值再让 demo 覆盖，测试结束自动还原，不污染其它测试。
    """
    from core import llm
    from scripts import demo_offline

    monkeypatch.setattr(llm, "_client", llm._client, raising=False)
    monkeypatch.setattr(real_agents, "web_search", real_agents.web_search, raising=False)
    monkeypatch.setattr(real_agents, "read_url", real_agents.read_url, raising=False)
    demo_offline._install_fake_llm()
    demo_offline._install_fake_search()

    if delay:
        client: Any = llm._client
        original_create = client.chat.completions.create

        def slow_create(*args: Any, **kwargs: Any) -> Any:
            time.sleep(delay)
            return original_create(*args, **kwargs)

        client.chat.completions.create = slow_create


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """离线桩 + TestClient。

    - 配置与归档库都重定向到 tmp_path，**绝不碰用户真实的 %APPDATA%/%LOCALAPPDATA%**
    - 退出时确保没有运行线程被遗留到测试之外
    """
    from core import config as app_config
    from core.storage import RunStore

    _install_stubs(monkeypatch)
    monkeypatch.setattr(app_config, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(api, "_store", RunStore(tmp_path / "runs.db"))
    with TestClient(api.app) as test_client:
        yield test_client
    active = api.registry.active()
    if active is not None:
        active.cancel.set()
        active.finished.wait(timeout=5)


@pytest.fixture()
def slow_client(tmp_path, monkeypatch):
    """每次 LLM 调用慢 0.15s，用来制造「运行中」这个窗口；配置/归档同样重定向到 tmp。"""
    from core import config as app_config
    from core.storage import RunStore

    _install_stubs(monkeypatch, delay=0.15)
    monkeypatch.setattr(app_config, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(api, "_store", RunStore(tmp_path / "runs.db"))
    with TestClient(api.app) as test_client:
        yield test_client
    active = api.registry.active()
    if active is not None:
        active.cancel.set()
        active.finished.wait(timeout=5)


def _wait_finished(client: TestClient, run_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/runs/{run_id}").json()
        if payload["status"] != "running":
            return payload
        time.sleep(0.05)
    raise AssertionError("运行未在超时内结束")


def _read_sse(client: TestClient, run_id: str, limit: int = 200) -> list[dict]:
    """读取 SSE 直到 end 帧；返回解析后的事件列表。"""
    events: list[dict] = []
    with client.stream("GET", f"/api/runs/{run_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("event: end"):
                break
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
            if len(events) >= limit:
                break
    return events


# --------------------------------------------------------------------- 用例
def test_health_and_static_frontend_are_both_served(client):
    assert client.get("/api/health").json()["ok"] is True

    index = client.get("/")
    assert index.status_code == 200
    assert "ResearchSwarm" in index.text  # 静态前端没被 /api 路由挡住


def test_run_streams_events_then_exposes_report_and_usage(client):
    created = client.post("/api/runs", json={"query": "AI Agent 的发展趋势"})
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    events = _read_sse(client, run_id)
    types = [e["type"] for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"
    assert types.count("step_started") == types.count("step_finished")

    detail = _wait_finished(client, run_id)
    assert detail["status"] == "finished"
    assert detail["stop_reason"] == "approved"
    assert "## 参考来源" in detail["report"]
    assert detail["sources"] and detail["sources"][0]["url"].startswith("https://")
    assert detail["usage"]["calls"] > 0
    assert detail["failures"] == {}


def test_cancel_endpoint_stops_the_run_before_writer(slow_client):
    run_id = slow_client.post("/api/runs", json={"query": "长时间调研"}).json()["run_id"]

    # 等第一个 Agent 跑完再取消，确保「运行中」这个窗口存在
    time.sleep(0.4)
    cancelled = slow_client.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["ok"] is True

    detail = _wait_finished(slow_client, run_id)
    assert detail["status"] == "cancelled"
    assert detail["cancelled"] is True
    assert not any(h["agent"] == "Writer" for h in detail["history"])


def test_second_concurrent_run_is_rejected(slow_client):
    first = slow_client.post("/api/runs", json={"query": "第一个"})
    assert first.status_code == 201

    second = slow_client.post("/api/runs", json={"query": "第二个"})
    assert second.status_code == 409
    assert "并发" in second.json()["detail"]

    slow_client.post(f"/api/runs/{first.json()['run_id']}/cancel")


def test_unknown_run_id_returns_404(client):
    assert client.get("/api/runs/does-not-exist").status_code == 404
    assert client.post("/api/runs/does-not-exist/cancel").status_code == 404


def test_empty_query_is_rejected_by_validation(client):
    assert client.post("/api/runs", json={"query": ""}).status_code == 422


# ----------------------------------------------------------- M4：配置与归档
def test_config_get_put_and_verify_never_leaks_the_key(client):
    initial = client.get("/api/config").json()
    assert "config_path" in initial

    saved = client.put("/api/config", json={"api_key": "sk-abcdefghijklmnop"}).json()
    assert saved["has_api_key"] is True
    assert saved["source"] == "config.json"  # 界面填的值优先于环境变量
    assert saved["api_key_masked"].startswith("sk-a")
    assert "sk-abcdefghijklmnop" not in json.dumps(saved, ensure_ascii=False)

    # 落盘后再读一次，仍然是掩码
    assert client.get("/api/config").json()["api_key_masked"].startswith("sk-a")

    # 验证接口用一次极小调用确认配置可用（测试里走的是桩客户端）
    verified = client.post("/api/config/verify").json()
    assert verified["ok"] is True


def test_demo_toggle_is_idempotent_and_restores_state(client):
    assert client.get("/api/demo").json()["enabled"] is False

    turned_on = client.post("/api/demo", json={"enabled": True}).json()
    assert turned_on["enabled"] is True and turned_on["changed"] is True

    again = client.post("/api/demo", json={"enabled": True}).json()
    assert again["changed"] is False  # 幂等

    turned_off = client.post("/api/demo", json={"enabled": False}).json()
    assert turned_off["enabled"] is False and turned_off["changed"] is True


def test_finished_run_is_archived_and_appears_in_history(client):
    run_id = client.post("/api/runs", json={"query": "归档测试"}).json()["run_id"]
    detail = _wait_finished(client, run_id)
    assert detail["status"] == "finished"
    assert detail["finished_at"]  # 归档需要结束时间

    history = client.get("/api/history").json()
    assert history["total"] >= 1
    assert any(row["run_id"] == run_id for row in history["runs"])
    assert history["runs"][0]["query"]


def test_export_endpoint_returns_markdown_attachment(client):
    run_id = client.post("/api/runs", json={"query": "导出测试"}).json()["run_id"]
    _wait_finished(client, run_id)

    response = client.get(f"/api/runs/{run_id}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert "# 导出测试" in response.text
    assert "## 参考来源" in response.text


def test_history_row_is_retrievable_after_registry_is_cleared(client):
    """模拟「进程重启」：内存注册表清空后，历史仍能从 SQLite 读回。"""
    run_id = client.post("/api/runs", json={"query": "持久化测试"}).json()["run_id"]
    _wait_finished(client, run_id)

    api.registry._runs.clear()  # 直接清掉内存记录，模拟重启
    api.registry._order.clear()

    archived = client.get(f"/api/runs/{run_id}")
    assert archived.status_code == 200
    body = archived.json()
    assert body["archived"] is True
    assert body["query"] == "持久化测试"
    assert body["report"]
