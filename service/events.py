"""运行事件契约：core 与前端之间的唯一接口。

设计要点
--------
1. **core 只产出结构化事件，不产出文案**。编排器不再 `print` —— 每个前端
   （CLI / FastAPI / 桌面窗口）自己决定怎么渲染。这是加 UI 的前提：
   同一套事件既能喂终端，也能喂 SSE 推给浏览器。
2. **本模块零依赖**（不 import core / agents / tools），所以任何前端都能安全引入它。
3. 事件是**不可变快照**（frozen dataclass），跨线程传递安全。
"""

from __future__ import annotations

import queue
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, cast, runtime_checkable

EventType = Literal[
    "run_started",      # 一次运行开始
    "step_started",     # 某个 Agent 开始执行
    "step_finished",    # 某个 Agent 执行结束（带耗时与当次用量）
    "round_started",    # 补研回边：进入新一轮
    "round_skipped",    # 补研回边：没有可补研的子任务，提前结束
    "rewrite_started",  # 评审打回，Writer 准备重写
    "run_finished",     # 正常结束（含 stop_reason）
    "run_cancelled",    # 被取消
]


def event_now() -> str:
    """本地时区 ISO 时间戳（与 core.state.now_iso 同口径，但此处零依赖）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class RunEvent:
    """一条运行事件。

    agent / duration_ms 只对部分事件有意义；其余信息放 data，
    这样新增字段不需要改事件类型，前端也能按需取用。
    """

    type: EventType
    at: str
    agent: str | None = None
    duration_ms: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的字典（FastAPI / SSE 直接用它）。"""
        return {
            "type": self.type,
            "at": self.at,
            "agent": self.agent,
            "duration_ms": self.duration_ms,
            "data": self.data,
        }


@runtime_checkable
class EventSink(Protocol):
    """事件出口：任何可调用对象（函数 / 实例的 __call__）都满足它。"""

    def __call__(self, event: RunEvent) -> None:  # pragma: no cover - 协议声明
        ...


def null_sink(event: RunEvent) -> None:
    """默认出口：丢弃所有事件（命令行以外的调用方不需要关心进度）。"""
    _ = event


def to_sink(on_event: EventSink | Callable[[RunEvent], None] | None) -> EventSink:
    """把「None / 普通函数 / sink 对象」统一成 EventSink。

    传 None 是合法用法（例如测试与批量脚本），此时返回丢弃式 sink。
    """
    if on_event is None:
        return null_sink
    if callable(on_event):
        return cast(EventSink, on_event)
    raise TypeError(f"on_event 必须是可调用对象，收到 {type(on_event)!r}")


class QueueSink:
    """线程安全的 sink：编排在工作线程产出，消费者在别的线程取。

    M2 的 FastAPI/SSE 就用它：`queue = QueueSink()` →
    `run_in_threadpool(run_swarm, query, on_event=queue)` → `for e in queue.iter_events()`。
    """

    def __init__(self) -> None:
        self.queue: queue.Queue[RunEvent | None] = queue.Queue()

    def __call__(self, event: RunEvent) -> None:
        self.queue.put(event)

    def close(self) -> None:
        """放入哨兵值，结束 iter_events() 的迭代。"""
        self.queue.put(None)

    def get(self, timeout: float | None = None) -> RunEvent | None:
        """取一条事件；返回 None 表示流已结束。"""
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def iter_events(self) -> Iterator[RunEvent]:
        while True:
            item = self.queue.get()
            if item is None:
                return
            yield item
