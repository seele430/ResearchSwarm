# ResearchSwarm

> **多 Agent 协作的深度研究系统**：Planner 拆解任务 → 多个 Researcher **并行**调研（搜索 + 抓正文）→ Analyst 综合并**报出信息缺口** → Planner 据此**追加子任务再调研一轮** → Writer 撰写报告 → Critic 评审打分，不合格打回重写。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Tests](https://img.shields.io/badge/tests-92%20passed-brightgreen.svg)
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
- **工程质量**：92 个 pytest 用例、`ruff` + `mypy` 全绿、GitHub Actions 双版本矩阵。

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

### 为什么真实 API 下远达不到 5x？

离线桩测的是**调度效率的上界**。真实环境还要受下游服务影响 —— 本项目早期在真实 API 下的实测是 **46 秒 → 23 秒（2.0x）**：

1. 搜索 API 对同一 IP 有并发限制
2. 多个请求共享同一出口带宽
3. 子任务耗时不均，快的要等慢的

**结论**：并行不是免费的，`RESEARCH_MAX_WORKERS` 要按下游承载能力来设。

```bash
# 用真实 API 测（会消耗 token）
python -m scripts.bench_research --live --tasks 5
```

---

## 🧪 测试与质量

```bash
pip install -r requirements-dev.txt
pytest -q          # 92 passed
ruff check .       # All checks passed!
mypy               # Success: no issues found in 14 source files
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

CI 见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)（Python 3.10 / 3.12 矩阵）。

---

## 📁 项目结构

```
ResearchSwarm/
├── main.py                      # 入口薄壳：调用 app/cli，并向后兼容再导出 CLI 辅助函数
├── app/
│   ├── __init__.py
│   └── cli.py                   # 命令行前端：订阅事件流渲染进度 + 保存报告 + rich 汇总
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
│   └── utils.py                 # 文件名净化与路径去重
├── tools.py                     # 工具集：搜索 / 正文抓取 / 笔记（失败一律抛异常）
├── scripts/
│   ├── bench_research.py        # 并联 vs 串联的可复现测量
│   ├── demo_offline.py          # 无 API Key 的离线演示
│   ├── smoke_llm.py             # 手工冒烟：真实调一次 LLM
│   └── smoke_search.py          # 手工冒烟：真实调一次搜索
├── tests/                       # 92 个 pytest 用例
├── docs/benchmark.md            # 由脚本生成的性能表格
├── docs/ui-plan.md              # UI 化改造方案（事件契约/取消语义/M1–M4 里程碑）
├── examples/sample-report.md    # 示例报告
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
- [x] **测试与 CI**：92 个用例 + ruff/mypy + 双版本矩阵
- [ ] **Web UI**：Streamlit / FastAPI 展示 Agent 实时协作过程
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
