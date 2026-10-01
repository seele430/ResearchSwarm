"""统一的 LLM 调用封装：客户端配置 + token 用量统计。

两点改进：

1. **显式 timeout / max_retries** —— OpenAI SDK 默认超时 600s，对 CLI 工具太宽松；
2. **用量计量**：每次调用把 `response.usage` 累加进全局 `USAGE`。
   Researcher 走线程池并发调用，所以累加必须加锁。
"""

from __future__ import annotations

import os
import threading
from dataclasses import replace
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from core.state import UsageStat

load_dotenv()

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2


class UsageMeter:
    """线程安全的 token 用量累加器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stat = UsageStat()

    def record(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int | None = None,
        calls: int = 1,
    ) -> None:
        with self._lock:
            prompt = int(prompt_tokens or 0)
            completion = int(completion_tokens or 0)
            total = int(total_tokens) if total_tokens is not None else prompt + completion
            self._stat = replace(
                self._stat,
                prompt_tokens=self._stat.prompt_tokens + prompt,
                completion_tokens=self._stat.completion_tokens + completion,
                total_tokens=self._stat.total_tokens + total,
                calls=self._stat.calls + calls,
            )

    def snapshot(self) -> UsageStat:
        with self._lock:
            return self._stat

    def reset(self) -> None:
        with self._lock:
            self._stat = UsageStat()


# 进程级计量器：一次 run_swarm 前 reset、结束后 snapshot
USAGE = UsageMeter()

# 客户端**懒加载**：绝不在 import 阶段校验密钥。
# 原因：桌面版（打包后的 exe）没有仓库里的 .env，如果在这里就构造 OpenAI(api_key=None)
# 会直接抛异常，导致整个应用打不开 —— 而正确行为是「能启动，跑的时候再报可操作的错」。
# 测试与离线演示会直接给 _client 赋值一个假客户端，懒加载逻辑要优先认它。
_client: OpenAI | None = None
_MODEL = (os.getenv("LLM_MODEL") or "").strip()


def _model_name() -> str:
    """模型名缺失时给出可操作的报错，而不是把 None 发给 API。"""
    if not _MODEL:
        raise RuntimeError("缺少 LLM_MODEL 配置：请在 .env 中设置（示例见 .env.example）")
    return _MODEL


def _get_client() -> OpenAI:
    """取（必要时创建）LLM 客户端；密钥缺失时给出能照着做的报错。"""
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少 LLM_API_KEY 配置：请在 .env 或环境变量中设置你的 API Key。"
            "（想先体验完整流程可以不配密钥，用离线演示模式：python -m app.desktop --demo）"
        )
    _client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL"),
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
    )
    return _client


def _record_usage(response: Any) -> None:
    """把一次响应的 usage 计入计量器（响应没有 usage 就跳过，不算错误）。"""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    USAGE.record(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", None),
    )


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """单轮对话，返回文本；token 用量自动计入 `USAGE`。"""
    resp = _get_client().chat.completions.create(
        model=_model_name(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    _record_usage(resp)
    # 少数情况下模型只返回工具调用、content 为 None，统一成空串避免 None 往下游泄漏
    return resp.choices[0].message.content or ""
