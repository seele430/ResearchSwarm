# UI 化改造方案（桌面软件化）

把 ResearchSwarm 从「终端脚本」变成「可双击运行的独立软件」。本文件是分阶段实施的设计基线，
每个里程碑都必须**可独立运行、可交付**。

## 目标形态

- 双击 `ResearchSwarm.exe` → 出现**自己的窗口**（不是浏览器标签、不依赖 VS Code）
- 界面里能看到：**5 个 Agent 的实时进度时间线**、报告正文、停止按钮、设置（API Key）
- 同一套 core，三个前端共用：CLI（现在）、FastAPI+Web（M2）、pywebview 桌面窗口（M3）

## 分层与依赖方向

```
web/             index.html + 原生 JS（前端，用户负责）
  ↓ HTTP / SSE
app/             api.py（FastAPI）  desktop.py（pywebview 开窗）  cli.py（终端）
  ↓ 调用 + 订阅事件
service/         events.py：运行事件契约（零依赖、跨线程安全）
  ↑ 产出事件
core/            orchestrator / state / llm / jsonx / utils   ← 不 print、不认识任何前端
agents/ tools.py 真实 Agent 与工具层
```

**铁律**：依赖只能向下。`core` 不许 import 任何前端；`service` 不许 import core。

## 事件契约（`service/events.py`）

| type | 何时发 | 关键字段 |
|---|---|---|
| `run_started` | 一次运行开始 | `data.query` / `data.started_at` |
| `step_started` | 某个 Agent 开始 | `agent` |
| `step_finished` | Agent 结束 | `agent`、`duration_ms`、`data.usage`、`data.plan`、`data.findings` |
| `round_started` | 进入补研回边 | `data.round`、`data.gaps`、`data.failures` |
| `round_skipped` | 无子任务可补研 | `data.reason="no_targets"` |
| `rewrite_started` | 评审打回、准备重写 | `data.revision`、`data.max_revisions` |
| `run_finished` | 正常结束 | `duration_ms`、`data.stop_reason`（`approved`/`max_revisions`/`finished`）、`data.usage`、`data.failures` |
| `run_cancelled` | 被取消 | `duration_ms`、`data.stage` |

`RunEvent.to_dict()` 直接可 JSON 序列化 → M2 的 SSE 不需要额外适配层。

## 取消语义

- `run_swarm(query, on_event=..., cancel=threading.Event())`
- 只在**步骤边界**检查（每个 Agent 调用前后）。置位后：已完成步骤与产出**全部保留**，
  立即返回，`state.cancelled = True`，并发出 `run_cancelled`。
- **不**强杀正在进行的 LLM 调用（要做得引入流式请求 + 超时，留到 M4）。
- Researcher 内部的 `ThreadPoolExecutor` 无法中途取消，同样在下一轮边界生效。

## 里程碑与验收标准

| 阶段 | 内容 | 验收 |
|---|---|---|
| **M1**（✅ 2026-10-01） | 事件契约 + 编排器去 print + 取消 + CLI 前端迁移 | 测试全绿；取消事件生效且不执行后续步骤；CLI 输出与改造前一致 |
| **M2**（✅ 2026-10-01） | `app/api.py`（FastAPI）+ SSE + `web/index.html`（卡片仪表盘） | 后端实测通过：静态前端与 API 共存、事件流完整、取消在步骤边界生效、并发 409；前端已完成卡片布局 + 安全迷你 Markdown 渲染 + 历史/来源/失败项 |
| **M3**（✅ 2026-10-01） | `app/desktop.py`（pywebview）+ PyInstaller + 图标 + 单实例 | 实测：双击 exe 出窗口、内部服务正常、**在 exe 里跑通完整流水线**（含补研回边）、重复双击被拦截、日志落 `%LOCALAPPDATA%` |
| **M4**（✅ 2026-10-01） | 设置面板（API Key / Base URL / 模型）· 演示模式一键切换 · SQLite 运行历史 · Markdown 导出 | 实测（含打包后的 exe）：配置只回传掩码、演示模式可切回真实调用、运行自动归档（重启后仍可查）、导出为 Markdown 附件 |

## 分工

- **AI**：事件层、编排器、API、打包、配置/归档/导出、前端界面与样式（M1–M4 全部完成）
- **用户**：验收（双击 exe 试用、真实 API 跑一单）、后续功能取舍（例如是否做代码签名 / 单文件分发）

## 兼容性约束（改代码时别踩）

1. `tests/` 里有 11 处 `run_swarm(<query>, verbose=False)` —— **`verbose` 参数必须继续接受**
   （已标记废弃，仅兼容）。
2. `tests/test_observability.py`、`tests/test_utils.py`、`scripts/demo_offline.py` 会
   `from main import build_report_path / build_summary_rows / print_run_summary` ——
   `main.py` 必须继续导出这三个名字（实现已搬到 `app/cli.py`，main 里只是再导出）。
3. `mypy` 的 `files` 已包含 `service` 与 `app` —— 新模块也要保持类型干净。

## Windows 目录规范（M3 落地）

| 用途 | 位置 |
|---|---|
| 配置（含 API Key） | `%APPDATA%\ResearchSwarm\config.json`（或 `keyring` 凭据管理器） |
| 日志 | `%LOCALAPPDATA%\ResearchSwarm\logs\` |
| 运行历史（SQLite） | `%LOCALAPPDATA%\ResearchSwarm\runs.db` |
| 用户报告输出 | 用户可选，默认「文档\ResearchSwarm\reports」 |
