"""离线演示模式：把 LLM 客户端与搜索换成桩，**并且可以还原**。

为什么需要它：
- 没有 API Key 的人（或面试演示现场）也要能完整跑一遍流水线；
- 桌面版如果只能靠命令行加 `--demo`，用户根本用不上 —— 所以设置界面上要能一键切换。

实现方式与 `scripts/demo_offline.py` 一致：只替换 LLM 客户端与搜索函数，
编排、补研回边、评审循环、来源汇总、观测全部走真实代码。
"""

from __future__ import annotations

import threading
from typing import Any, cast

_lock = threading.Lock()
_enabled = False
_snapshot: dict[str, Any] = {}


def is_enabled() -> bool:
    return _enabled


def enable() -> bool:
    """打开演示模式；已打开则返回 False（幂等）。"""
    global _enabled, _snapshot
    from agents import real_agents
    from core import llm
    from scripts import demo_offline

    with _lock:
        if _enabled:
            return False
        _snapshot = {
            "llm_client": llm._client,
            "llm_client_key": llm._client_key,
            "web_search": real_agents.web_search,
            "read_url": real_agents.read_url,
        }
        demo_offline._install_fake_llm()
        demo_offline._install_fake_search()
        _enabled = True
        return True


def disable() -> bool:
    """关闭演示模式并还原真实实现；未开启则返回 False（幂等）。"""
    global _enabled, _snapshot
    from agents import real_agents
    from core import llm

    with _lock:
        if not _enabled:
            return False
        if _snapshot:
            llm._client = _snapshot.get("llm_client")
            llm._client_key = _snapshot.get("llm_client_key")
            # cast 成 Any：还原的是运行时对象，静态类型上只需让检查器放行
            real_agents.web_search = cast(Any, _snapshot.get("web_search"))
            real_agents.read_url = cast(Any, _snapshot.get("read_url"))
        _snapshot = {}
        _enabled = False
        return True
