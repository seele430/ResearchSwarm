# HTTP / SSE 接口契约（M2）

后端入口：`python -m app.api`。默认监听 `127.0.0.1:8756`，静态前端挂在 `/`（与 API 同源，无 CORS）。
加 `--demo` 走离线桩（假 LLM + 假搜索，**真实流水线**，不联网、不花 token），用来做界面联调与演示。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | `web/index.html`（静态资源同源提供） |
| GET | `/api/health` | `{"ok": true, "active_run": null \| "<run_id>"}` |
| GET | `/api/runs` | 最近运行列表（内存注册表，最多保留 50 条） |
| POST | `/api/runs` | 请求体 `{"query": "..."}`（1–500 字）→ `201 {"run_id": "...", "status": "running"}` |
| GET | `/api/runs/{run_id}` | 运行快照（内存优先；进程重启后回落 SQLite 归档，此时带 `archived: true`） |
| GET | `/api/runs/{run_id}/events` | **SSE** 事件流；先回放缓冲，再增量推送，结束时发 `event: end` |
| POST | `/api/runs/{run_id}/cancel` | 请求取消 → `{"ok": true, "status": "cancelling"}`；已结束则 `{"ok": false, ...}` |
| GET | `/api/history?limit=20` | 归档历史（SQLite，按结束时间倒序；列表不含报告正文） |
| GET | `/api/runs/{run_id}/export` | 导出 Markdown 附件（报告 + 来源清单 + 用量元信息） |
| GET | `/api/config` | 当前配置（**只含密钥掩码**，无明文） |
| PUT | `/api/config` | 保存配置（`api_key` / `base_url` / `model`，只更新传入的字段） |
| POST | `/api/config/verify` | 用一次极小调用验证配置是否可用（演示模式下不调用真实模型） |
| GET | `/api/demo` | 演示模式状态 |
| POST | `/api/demo` | 切换演示模式：`{"enabled": true}` → `{"enabled": ..., "changed": ...}` |

### 错误码

| 码 | 场景 |
|---|---|
| 404 | `run_id` 不存在 |
| 409 | 已有运行在进行中（`core.llm.USAGE` 是进程级计量器，暂不支持并发，M4 会改） |
| 422 | `query` 为空或超长（pydantic 校验） |

## 运行快照（`GET /api/runs/{run_id}`）

```json
{
  "run_id": "8be5d4adf098",
  "query": "AI Agent 的发展趋势",
  "status": "finished",              // running | finished | cancelled | failed
  "stop_reason": "approved",         // approved | max_revisions | finished | cancelled
  "event_count": 19,
  "duration_ms": 4,
  "error": "",
  "started_at": "2026-10-01T19:02:23+08:00",
  "cancelled": false,
  "plan": ["调研背景", "调研现状", "补充调研 2026 年最新数据"],
  "report": "# 研究报告\n\n## 结论\n结论基于两轮调研 [1]。\n\n## 参考来源\n1. ...",
  "analysis": "分析正文 [1]",
  "critique": "合格",
  "approved": true,
  "revision_count": 0,
  "research_rounds": 1,
  "failures": {},
  "findings": { "调研背景": 12, "调研现状": 12 },
  "sources": [{ "title": "调研背景 的来源", "url": "https://example.com/1" }],
  "usage": { "prompt_tokens": 2700, "completion_tokens": 810, "total_tokens": 3510, "calls": 9 },
  "history": [{ "agent": "Planner", "action": "步骤完成", "at": "...", "duration_ms": 0 }]
}
```

## SSE 事件帧

每帧格式：`data: <RunEvent JSON>\n\n`，结束时多一帧 `event: end\ndata: {}\n\n`。
`RunEvent` 结构（字段含义见 [ui-plan.md](ui-plan.md) 的事件表）：

```json
{ "type": "step_finished", "at": "2026-10-01T19:02:23+08:00", "agent": "Planner",
  "duration_ms": 0, "data": { "usage": {"calls": 1, "total_tokens": 390}, "plan": 2, "findings": 0 } }
```

前端最小接入（与 `web/index.html` 里已实现的写法一致）：

```js
const { run_id } = await (await fetch("/api/runs", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query }),
})).json();

const es = new EventSource(`/api/runs/${run_id}/events`);
es.onmessage = (m) => renderEvent(JSON.parse(m.data));          // 逐条渲染时间线
es.addEventListener("end", async () => {
  es.close();
  const detail = await (await fetch(`/api/runs/${run_id}`)).json();  // 取报告/来源/用量
  renderReport(detail);
});
```

**停止**：`POST /api/runs/{run_id}/cancel`。取消在**步骤边界**生效 —— 当前正在进行的 LLM 调用会跑完，
已完成的产出全部保留，随后事件流收到 `run_cancelled`。

## 已知限制

1. **不能并发**：`core.llm.USAGE` 为进程级计量器，同时只允许一个运行（并发请求 409）。M4 改成按运行计量。
2. **注册表在内存里**：重启服务后历史运行丢失（M4 换 SQLite）。
3. **无鉴权**：只监听 `127.0.0.1`，定位是本机桌面应用；M3 打包后同样只绑定回环地址。
