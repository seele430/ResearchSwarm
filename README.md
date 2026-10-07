# ResearchSwarm

> **多 Agent 协作的深度研究系统**：Planner 拆解任务 → 多个 Researcher **并行**调研（搜索 + 抓正文）→ Analyst 综合并**报出信息缺口** → Planner 据此**追加子任务再调研一轮** → Writer 撰写报告 → Critic 评审打分，不合格打回重写。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Tests](https://img.shields.io/badge/tests-140%20passed-brightgreen.svg)
![Quality](https://img.shields.io/badge/ruff%20%2B%20mypy-clean-blueviolet.svg)

---

## ✨ 特性

以下每条都对应代码里的**可验证行为**，括号里是验证方式：

### 编排：不只是单向流水线

- **5 个角色 + 补研回边**：Analyst 输出结构化的 `gaps`（信息缺口）→ Planner 把缺口改写成**可检索的新子任务** → Researcher 只对「新增 + 失败重试」项再跑一轮（`MAX_RESEARCH_ROUNDS`，默认 1 轮）。
  *验证：`tests/test_replan.py` 断言第二轮只调研新增项、轮次被上限封顶。*
- **评审闭环语义明确**：Critic 打 0–10 分；`MAX_REVISIONS = 2` 的确切含义是**最多重写 2 次**（Writer 最多被调用 3 次）。
  *验证：`tests/test_review_loop.py` 断言 `writer_calls == [0, 1, 2]`。*

### 调研质量

- **并行调研**：`ThreadPoolExecutor`，并发度由 `RESEARCH_MAX_WORKERS` 控制。
- **正文抓取**：每个子任务对排名靠前的结果**抓正文**（trafilatura → BeautifulSoup 两级降级），失败则退回摘要并**在 prompt 里如实标注**「正文抓取失败」。
- **可核验来源**：搜索结果带编号进入 prompt；报告末尾由程序追加 `## 参考来源` 清单 —— URL 直接取自搜索 API，**不经过模型生成**，模型漏写也不会导致报告没有出处。
  *验证：`tests/test_sources.py` 断言正文进入 prompt、抓取失败退化、重复 URL 去重、报告末尾有真实链接。*
- **失败显式记账**：搜索/提炼失败写入 `state.failures` 并作为「信息缺口」传给 Analyst/Writer，**绝不把报错文本当成调研结果**喂给模型。
  *验证：`tests/test_research_failures.py` 断言 `test_error_text_never_leaks_into_findings`。*

### 工程

- **结构化输出加固**：`core/jsonx.py` 采用「多候选提取 + 括号配对扫描 + 字段校验」，`"approved": "true"`、`"score": "9"`、内容里含 ``` 都能正确解析。
  *验证：`tests/test_json_parsing.py`（27 个用例）。*
- **可观测**：`history` 带时间戳与每步耗时，token 用量自动计量，运行结束用 rich 打汇总表。
- **工程质量**：**140 个 pytest 用例全部通过**、`ruff` + `mypy` 全绿、GitHub Actions 双版本矩阵。

---

## 🏗️ 架构

```
                        用户提问
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │      Orchestrator（编排器）           │
        │  · 共享状态 SwarmState               │
        │  · 调度 Agent、计时、统计 token       │
        └──────────────────────────────────────┘
                           │
      ┌────────────────────┼────────────────────┐
      ▼                    ▼                    ▼
 ┌─────────┐         ┌──────────┐        ┌──────────┐
 │ Planner │ ──────▶ │Researcher│ ─────▶ │ Analyst  │
 │ 拆解任务 │         │ 并行调研  │        │ 分析+报缺口│
 └─────────┘         └──────────┘        └────┬─────┘
      ▲                                        │
      │           ① 有缺口 / 有失败             │
      └──────── Planner(补研) ◀────────────────┘
                 只调研「新增 + 失败重试」项
                                               │
                                               ▼
                                    ┌───────────────────┐
                                    │  Writer ⇄ Critic  │
                                    │  撰写 ⇄ 评审打分   │
                                    │  最多重写 MAX_REVISIONS 次 │
                                    └───────────────────┘
                                               │
                                               ▼
                                    最终报告（附来源清单）
```

### 5 个角色的职责

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **Planner** | 把问题拆成 3–5 个可执行子任务；补研轮把缺口改写成新子任务 | 用户问题 / 缺口列表 | 子任务列表 |
| **Researcher** | 对每个子任务**并行**搜索 + 抓正文 + 提炼 | 子任务列表 | 调研结论 + 来源 |
| **Analyst** | 综合所有材料、识别矛盾、**报出信息缺口** | 调研结论 + 来源 | `analysis` + `gaps` |
| **Writer** | 撰写结构化报告，按 `[编号]` 标注引用 | 分析 + 来源 | 报告草稿 |
| **Critic** | 评审报告（0–10 分），不合格打回 | 报告草稿 | 评审意见 + 是否通过 |

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- LLM API Key（推荐 [DeepSeek](https://platform.deepseek.com)）
- 搜索 API Key（推荐 [博查 Bocha](https://open.bochaai.com)）

### 2. 安装

```bash
git clone https://github.com/seele430/ResearchSwarm.git
cd ResearchSwarm

python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt          # 仅运行时
# 或者装开发依赖（含 pytest / ruff / mypy）
pip install -r requirements-dev.txt
```

### 3. 配置

复制 `.env.example` 为 `.env`，填入自己的密钥：

```env
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
BOCHA_API_KEY=your_bocha_api_key_here
```

### 4. 运行

```bash
python main.py
# 输入研究问题，例如：AI Agent 的发展趋势
```

报告会保存到 `notes/`（文件名已做净化与去重，含`:?*`的问题不会崩，重复运行不会互相覆盖）。

### 5. 不想花 API 额度？跑离线演示

```bash
python -m scripts.demo_offline     # 用假 LLM 客户端跑真实流水线（含补研回边）
```

---

## 📊 性能：并联 vs 串联

数字**不再是手工填的**，由 `scripts/bench_research.py` 实测产出：

| 模式 | 实现方式 | 耗时 | 加速比 | 成功/失败 |
|------|---------|------|--------|-----------|
| 串联 | `ThreadPoolExecutor(max_workers=1)` | 12.01 s | 1.00x | 5/0 |
| 并联 | `ThreadPoolExecutor(max_workers=5)` | 2.40 s | **5.00x** | 5/0 |

> 条件：离线桩（固定延迟：搜索 0.8s / 抓正文 0.3s / 提炼 1.0s）、5 个子任务、2 次取中位数、Python 3.12.7。
> 完整表格见 [`docs/benchmark.md`](docs/benchmark.md)；复现：`python -m scripts.bench_research --tasks 5 --repeat 2`

### 真实 API 下能拿到多少加速？

**同一个脚本加 `--live` 就能测**，但结果随下游状态波动很大，所以别把它当成一个固定数字：

| 测量时间 | 串联 | 并联 | 加速比 |
|---------|------|------|--------|
| 2026-10-07 | 36.84 s | 7.21 s | **5.11x** |
| 项目早期 | 46 s | 23 s | 2.0x |

两次测的是**同一件事**（Researcher 阶段、5 子任务、取中位数），结果却相差约 2.5 倍 ——
这说明该加速比高度依赖测量时下游的承载状态，而不是一个常数。可能压低收益的因素：

1. 搜索 API 对同一 IP 有并发限制
2. 多个请求共享同一出口带宽
3. 子任务耗时不均，快的要等慢的

完整输出见 [`docs/benchmark-live.md`](docs/benchmark-live.md)。

**结论**：并行不是免费的，`RESEARCH_MAX_WORKERS` 要**实测**下游承载能力来设，而不是照抄一个数字。

```bash
# 用真实 API 测（会消耗 token）
python -m scripts.bench_research --live --tasks 5
```

---

## 🖥️ Web 界面（M2）

```bash
python -m app.api --demo     # 离线演示：假 LLM + 假搜索，真实流水线；不联网、不花 token
# 浏览器打开 http://127.0.0.1:8756/
```

- 后端：FastAPI + **SSE 事件流** —— 完整接口契约见 [docs/api.md](docs/api.md)
- 前端：`web/index.html`（可运行的极简骨架：Agent 时间线 / 报告 / 停止按钮；界面仍在迭代）
- 去掉 `--demo` 即真实调用；`--port` 可换端口
- **停止**在步骤边界生效：当前 LLM 调用会跑完，已完成产出全部保留（事件流收到 `run_cancelled`）
- 同时只允许一个运行（token 计量器是进程级的），并发请求返回 409

---

## 🖥️ 桌面版（M3）

```bash
# 开发时直接开窗
venv\Scripts\python.exe -m app.desktop --demo

# 打包出可双击运行的 exe
venv\Scripts\python.exe scripts\build_exe.py              # 目录版 → dist\ResearchSwarm\ResearchSwarm.exe
venv\Scripts\python.exe scripts\build_exe.py --onefile    # 单文件版 → dist\single\ResearchSwarm.exe
venv\Scripts\python.exe scripts\build_exe.py --console    # 控制台调试版（排查启动异常）
# 目录版：exe 约 15 MB，整目录约 96 MB（约 2600 个文件，必须整目录分发）
# 单文件版：约 48 MB 的单个 exe
```

- **窗口**：pywebview 复用系统自带的 **WebView2**（Win11 已预装），不打包浏览器内核、不用 Electron/Node
- **单实例**：独占锁端口 8755；重复双击会直接退出，不会开出一堆窗口
- **动态端口**：默认 8756，被占用时自动换；实际端口写入 `%LOCALAPPDATA%\ResearchSwarm\last-run.json`
- **无控制台也能排查**：标准流被接到 `%LOCALAPPDATA%\ResearchSwarm\logs\desktop.log`
- **两种形态怎么选**（实测数据）：**目录版** `dist\ResearchSwarm\`（exe 15 MB + `_internal`，**冷启动约 3.6 秒**），自己日常用；
  **单文件版** `dist\single\ResearchSwarm.exe`（**48.2 MB 一个文件**，发给别人最省事，**冷启动约 9–10 秒** —— 每次启动都要自解压到 `%TEMP%\_MEIxxxx`，正常退出时自动清理）。
  单文件版已实测：窗口正常、完整流水线、历史归档、Markdown 导出、单条删除与清空全部全部可用；关窗口后父/子进程都会退出并清理临时目录
- **打包要点**（都写进 `scripts/build_exe.py` 了）：`--add-data web;web` 带前端、`--collect-all webview` 带 WebView2 的 .NET DLL、`--collect-data trafilatura` 带抓正文的数据文件、uvicorn 的多个动态导入用 `--hidden-import` 显式声明；排查启动异常时加 `--console` 出控制台版
- **已知边界**：exe 尚未代码签名，首次运行 Windows SmartScreen 可能提示
- **桌面快捷方式**：`%USERPROFILE%\Desktop\ResearchSwarm.lnk`（指向 `dist` 里的 exe；删掉 `dist` 后需重建）
- **发给别人用**：发布目录里会自动带上 [`使用说明.txt`](使用说明.txt)（含"去哪注册 DeepSeek API、怎么填 Key、常见问题"），
  压缩整个 `dist\ResearchSwarm` 目录一起发即可 —— **只发 exe 是跑不起来的**（onedir 结构必须有 `_internal`）
- **数据都在对方本机**：历史 `%LOCALAPPDATA%\ResearchSwarm\runs.db`、配置 `%APPDATA%\ResearchSwarm\config.json`、
  日志 `%LOCALAPPDATA%\ResearchSwarm\logs\` —— **发布包里不含任何运行记录或密钥**（已实测：包内无 db/配置/日志，且搜不到任何 Key）；
  换一台电脑安装后历史是空的，程序只监听 `127.0.0.1`，同一局域网内其他机器也访问不到
- **设置面板（M4）**：界面里填 API Key / Base URL / 模型 → 存到 `%APPDATA%\ResearchSwarm\config.json`
  （**接口只回传掩码，从不回传明文**）；「验证」按钮用一次极小调用确认配置真的可用
- **演示模式开关（M4）**：设置里一键切换（离线桩 + 真实流水线），**没有 API Key 也能完整演示**
- **运行历史（M4）**：运行结束自动归档到 `%LOCALAPPDATA%\ResearchSwarm\runs.db`（SQLite），
  界面左侧可点开历史；**「导出 Markdown」**把报告 + 来源清单 + 用量下载成文件；服务重启后历史仍在

---

## 🧪 测试与质量

```bash
pip install -r requirements-dev.txt
pytest -q          # 140 passed
ruff check .       # All checks passed!
mypy               # Success: no issues found in 21 source files
```

| 测试文件 | 覆盖内容 |
|---|---|
| `test_dependencies.py` | **代码 import 的依赖必须在 requirements 里声明**（防"全新安装就 ImportError"） |
| `test_json_parsing.py` | 代码块/夹带正文/含 ``` 的 JSON、布尔与分数容错、Planner 降级 |
| `test_utils.py` | 文件名净化（非法字符、保留设备名、长度、去重） |
| `test_research_failures.py` | 搜索失败不入 findings、重试、部分失败保留成功项、缺口注入 prompt |
| `test_review_loop.py` | Writer⇄Critic 轮次语义、Critic 不推进计数、评审失败 fail-open |
| `test_sources.py` | 正文抓取、抓取失败退化、来源去重、报告来源清单 |
| `test_observability.py` | 时间戳/耗时、token 计量（含并发累加）、汇总表 |
| `test_replan.py` | 补研回边：触发条件、轮次上限、失败重试与撤销 |
| `test_pipeline_offline.py` | 离线端到端：五角色齐全、报告带真实来源 |
| `test_events.py` | 事件契约：step 配对与顺序、取消（Writer 前 / 一开始）、QueueSink 跨线程、to_sink 入参、事件不可变 |
| `test_api.py` | HTTP/SSE 后端：静态前端与 API 共存、事件流完整、取消在步骤边界生效、并发 409、404/422 |
| `test_config.py` | 配置优先级（文件 > 环境变量）、合并写入、密钥掩码、不泄漏明文 |
| `test_storage.py` | SQLite 归档往返、幂等更新、轻量列表、Markdown 导出 |
| `test_desktop.py` | 端口选择、单实例互斥、运行信息落盘、无标准流时的日志重定向回归 |

CI 见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)（Python 3.10 / 3.12 矩阵）。

---

## 📁 项目结构

```
ResearchSwarm/
├── main.py                      # 入口薄壳：调用 app/cli，并向后兼容再导出 CLI 辅助函数
├── run_desktop.py               # 桌面版入口（PyInstaller 的入口脚本；开发时也可直接跑）
├── assets/icon.ico              # 应用图标（打包进 exe）
├── app/
│   ├── __init__.py
│   ├── cli.py                   # 命令行前端：订阅事件流渲染进度 + 保存报告 + rich 汇总
│   ├── api.py                   # FastAPI + SSE 后端：运行 / 配置 / 历史 / 导出 / 演示模式
│   ├── desktop.py               # 桌面窗口（M3）：pywebview + 单实例 + 动态端口 + 日志重定向
│   ├── demo.py                  # 演示模式开关（离线桩，可随时还原）
│   └── export.py                # 运行导出 Markdown（纯函数，便于测试）
├── web/
│   └── index.html               # 前端骨架：Agent 时间线 / 报告 / 停止按钮（界面迭代中）
├── service/
│   ├── __init__.py
│   └── events.py                # 运行事件契约（结构化、零依赖、跨线程安全）
├── agents/
│   ├── __init__.py
│   └── real_agents.py           # 5 个角色的真实实现（prompt + 工具 + 降级策略）
├── core/
│   ├── __init__.py
│   ├── state.py                 # SwarmState：共享状态 + 观测数据（history/usage/sources）
│   ├── llm.py                   # LLM 客户端（超时/重试）+ 线程安全 token 计量
│   ├── jsonx.py                 # 结构化输出解析与校验（Planner/Analyst/Critic 共用）
│   ├── orchestrator.py          # 编排：主线 + 补研回边 + 评审闭环 + 计时（产出事件流，不 print）
│   ├── config.py                # 用户配置：config.json 优先于环境变量，只对外给密钥掩码
│   ├── storage.py               # 运行历史归档（SQLite，重启后历史仍在）
│   └── utils.py                 # 文件名净化与路径去重
├── tools.py                     # 工具集：搜索 / 正文抓取 / 笔记（失败一律抛异常）
├── scripts/
│   ├── bench_research.py        # 并联 vs 串联的可复现测量
│   ├── build_exe.py             # M3：PyInstaller 打包（onedir + 图标 + 静态资源 + hidden imports）
│   ├── demo_offline.py          # 无 API Key 的离线演示
│   ├── smoke_llm.py             # 手工冒烟：真实调一次 LLM
│   └── smoke_search.py          # 手工冒烟：真实调一次搜索
├── tests/                       # 140 个 pytest 用例（全部通过）
├── docs/benchmark.md            # 由脚本生成的性能表格（离线桩，可复现）
├── docs/benchmark-live.md       # 由脚本生成的性能表格（真实 API，随下游波动）
├── docs/ui-plan.md              # UI 化改造方案（事件契约/取消语义/M1–M4 里程碑）
├── docs/api.md                  # HTTP/SSE 接口契约（M2 前端对接用）
├── examples/sample-report.md    # 示例报告
├── examples/demo-offline-output.md  # 离线 demo 输出（含来源清单格式）
├── notes/                       # 运行产物（gitignore）
├── pyproject.toml               # ruff / mypy 配置
├── pytest.ini
├── requirements.txt
├── requirements-dev.txt
├── DECISIONS.md                 # 工程决策日志（001–010）
└── README.md
```

---

## 🧠 设计决策

完整的「为什么这么做、代价是什么」见 [`DECISIONS.md`](DECISIONS.md)：Agent 数量取舍、共享状态 vs 消息传递、并行度、评审闭环、结构化输出、失败记账、来源可核验、补研回边、可观测口径。

---

## 🗺️ Roadmap

- [x] **补研回边**：Analyst 报缺口 → Planner 追加子任务再调研（真正的多 Agent 协作）
- [x] **可观测**：每步耗时、token 用量、执行日志带时间戳
- [x] **可复现性能测量**：`scripts/bench_research.py`
- [x] **测试与 CI**：140 个用例（含 HTTP/SSE 后端测试与事件契约测试）+ ruff/mypy + 双版本矩阵
- [x] **Web UI**：FastAPI + SSE 实时展示 Agent 协作过程（M2 已完成）
- [ ] **持久化记忆**：`SwarmState` 落库，支持中断恢复
- [ ] **更多工具**：PDF 解析、代码执行、图表生成
- [ ] **评估体系**：用 RAGAS 等框架量化报告质量
- [ ] **Human-in-the-loop**：关键节点允许人工介入

---

## 📄 License

MIT

---

## 🙏 致谢

- [DeepSeek](https://platform.deepseek.com) — LLM 服务
- [博查 Bocha](https://open.bochaai.com) — 搜索 API
- [trafilatura](https://github.com/adbar/trafilatura) — 网页正文提取
- [rich](https://github.com/Textualize/rich) — 终端汇总表
