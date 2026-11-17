# ResearchSwarm

一个多 Agent 调研工具，提供命令行、Web 和 Windows 桌面三种界面。输入问题后，Planner 拆任务，多个 Researcher 并行检索，Analyst 汇总并找出缺口，Writer 写报告，Critic 决定是否打回重写。

## 工作流程

```text
Planner 拆解问题
  → Researcher 并行搜索、读取正文和提炼
  → Analyst 综合分析，列出信息缺口
  → Planner 按需追加子任务，再补研一轮
  → Writer 撰写报告
  → Critic 评审，必要时交回 Writer 修改
```

默认最多补研 1 轮，由 `MAX_RESEARCH_ROUNDS` 控制。`MAX_REVISIONS = 2` 表示最多重写 2 次，也就是 Writer 最多执行 3 次。

### 来源与失败处理

- Researcher 使用 `ThreadPoolExecutor` 并行工作，并发度由 `RESEARCH_MAX_WORKERS` 控制。
- 网页正文先由 trafilatura 提取，失败后尝试 BeautifulSoup，再退回搜索摘要并标记抓取失败。
- 报告末尾的参考来源由程序根据搜索 API 返回的 URL 追加，不依赖模型重新写出链接。
- 搜索和提炼失败进入 `state.failures`，不会作为调研结论传给后续 Agent。
- Analyst 返回结构化 `gaps`，补研轮只处理新增任务和失败重试项。

结构化输出解析、事件流、token 统计和运行历史分别位于 `core/jsonx.py`、`service/events.py`、`core/llm.py` 和 `core/storage.py`。

## 安装

需要 Python 3.10+。真实调研需要模型 API Key 和博查搜索 API Key；离线演示不需要密钥。

```bash
git clone https://github.com/seele430/ResearchSwarm.git
cd ResearchSwarm

python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
# 开发和测试：pip install -r requirements-dev.txt
```

复制 `.env.example` 为 `.env`：

```env
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
BOCHA_API_KEY=your_bocha_api_key_here
```

## 命令行

```bash
python main.py
```

报告保存在 `notes/`。文件名会清理非法字符并避免覆盖已有文件。

不调用外部 API 的演示：

```bash
python -m scripts.demo_offline
```

演示使用假模型和假搜索数据，但会经过真实的编排、补研和评审代码。

## Web 界面

```bash
python -m app.api --demo
```

打开 <http://127.0.0.1:8756/>。去掉 `--demo` 后使用真实配置，`--port` 可以修改端口。

后端使用 FastAPI 和 SSE，前端是 `web/index.html`。接口定义见 [docs/api.md](docs/api.md)。

停止操作在步骤边界生效：当前模型调用结束后停止，已完成的产出会保留。服务同时只允许一个运行，并发请求返回 409。

## Windows 桌面版

桌面窗口使用 pywebview 和系统 WebView2，服务只监听本机回环地址。

```powershell
# 开发模式
venv\Scripts\python.exe -m app.desktop --demo

# PyInstaller 目录版
venv\Scripts\python.exe scripts\build_exe.py

# 单文件版
venv\Scripts\python.exe scripts\build_exe.py --onefile

# 带控制台的调试版
venv\Scripts\python.exe scripts\build_exe.py --console
```

目录版位于 `dist\ResearchSwarm\`，必须连同 `_internal` 一起分发；单文件版位于 `dist\single\ResearchSwarm.exe`，启动时需要先自解压。exe 尚未代码签名，Windows SmartScreen 可能提示。

设置、历史和日志的位置：

```text
配置：%APPDATA%\ResearchSwarm\config.json
历史：%LOCALAPPDATA%\ResearchSwarm\runs.db
日志：%LOCALAPPDATA%\ResearchSwarm\logs\
端口：%LOCALAPPDATA%\ResearchSwarm\last-run.json
```

配置接口只返回密钥掩码。历史可以回看、导出 Markdown、单条删除或清空。随安装包分发的操作说明见 [使用说明.txt](使用说明.txt)。

## 测试

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check .
mypy
```

测试覆盖 JSON 解析、补研回边、评审轮次、来源清单、失败记账、事件契约、HTTP/SSE、配置、存储和桌面启动。CI 配置见 [.github/workflows/ci.yml](.github/workflows/ci.yml)。

## 并行度测量

```bash
# 离线桩
python -m scripts.bench_research --tasks 5 --repeat 2

# 真实 API，会消耗额度
python -m scripts.bench_research --live --tasks 5
```

离线结果见 [docs/benchmark.md](docs/benchmark.md)，真实 API 记录见 [docs/benchmark-live.md](docs/benchmark-live.md)。真实加速比会受搜索限流、网络、模型延迟和子任务耗时差异影响，应根据下游承载能力调整并发度。

## 目录

```text
ResearchSwarm/
├── agents/real_agents.py   # 五个角色的 prompt、工具与降级策略
├── app/                    # CLI、FastAPI/SSE、桌面窗口与导出
├── core/                   # 状态、编排、配置、存储和结构化输出
├── service/events.py       # 运行事件契约
├── web/index.html          # Web 前端
├── scripts/                # 演示、基准、打包与冒烟脚本
├── tests/                  # pytest 测试
├── docs/                   # 接口、性能和 UI 设计记录
├── examples/               # 示例输出
└── DECISIONS.md            # 技术决策记录
```

## 已知限制

- `SwarmState` 尚未完整持久化，中断后不能从任意步骤恢复。
- Web 服务同时只处理一个运行，停止不会中断正在执行的单次模型请求。
- 报告中的结论仍需人工核对；来源清单可验证链接出处，但不保证来源本身可靠。
- Windows 打包版未签名，单文件版启动比目录版慢。

设计取舍见 [DECISIONS.md](DECISIONS.md)。

## License

MIT
