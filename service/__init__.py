"""服务层：前端与 core 之间的接口层。

- `events`：运行事件契约（结构化、零依赖、跨线程安全）
- 后续里程碑会在这里加入运行注册表（run_id → 状态/取消/历史）
"""

from service.events import EventSink, QueueSink, RunEvent, null_sink, to_sink

__all__ = ["EventSink", "QueueSink", "RunEvent", "null_sink", "to_sink"]
