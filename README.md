# ResearchSwarm

> **一个基于多 Agent 协作的深度研究系统：Planner 拆解任务 → 多个 Researcher 并行调研 → Analyst 综合分析 → Writer 撰写报告 → Critic 质量把关，形成完整的"研究-写作-评审"闭环。**

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Multi-Agent](https://img.shields.io/badge/Multi--Agent-5_roles-purple.svg)
---

## ✨ Features / 特性

- **🤖 多 Agent 协作**：5 个角色分工明确（Planner / Researcher / Analyst / Writer / Critic），各司其职
- **⚡ 并行调研**：多个子任务由线程池并发执行，相比串行提速 3-5 倍
- **🔄 反馈循环**：Critic 评审不合格会打回 Writer 重写，最多迭代 2 次，保证报告质量
- **📊 结构化状态**：所有 Agent 共享一份 `SwarmState`，全流程可观测
- **🌐 真实联网**：Researcher 调用博查搜索 API，不依赖预训练知识
- **🎯 自我反思**：Critic 带 0-10 评分机制，量化报告质量
- **📝 完整交付**：含架构图、示例报告、决策日志、性能对比
---

## 🏗️ Architecture / 架构

```
                       用户提问
                          │
                          ▼
        ┌─────────────────────────────────────┐
        │       Orchestrator（编排器）        │
        │  - 管理共享状态 SwarmState          │
        │  - 调度 Agent 执行顺序              │
        │  - 控制评审-重写循环                │
        └─────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   ┌─────────┐      ┌──────────┐      ┌──────────┐
   │ Planner │ ───▶ │Researcher│ ───▶ │ Analyst  │
   │ 拆解任务 │      │ 并行调研  │      │ 综合分析  │
   └─────────┘      └──────────┘      └──────────┘
                          │
                          ▼
                  ┌───────────────┐
                  │ Writer ⇄ Critic│
                  │ 撰写 ⇄ 评审    │
                  │ （最多迭代 2 次）│
                  └───────────────┘
                          │
                          ▼
                    最终研究报告
```

### 5 个 Agent 的职责

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **Planner** | 把用户问题拆解成 3-5 个可执行的子任务 | 用户问题 | 子任务列表 |
| **Researcher** | 对每个子任务**并行**搜索 + 提炼关键信息 | 子任务列表 | 调研结果 |
| **Analyst** | 综合分析所有调研结果，识别矛盾 | 调研结果 | 结构化分析 |
| **Writer** | 撰写结构化研究报告 | 分析内容 | 报告草稿 |
| **Critic** | 评审报告质量（0-10 评分） | 报告草稿 | 评审意见 + 是否通过 |

### 核心设计

- **共享状态**：所有 Agent 读写同一份 `SwarmState`，无需点对点通信
- **流水线 + 闭环**：前 3 步是流水线（Planner → Researcher → Analyst），后 2 步是闭环（Writer ⇄ Critic）
- **可观测**：每一步都有 `history` 日志，可回溯整个执行过程
---

## 🚀 Quick Start / 快速开始

### 1. 环境要求

- Python 3.10+
- LLM API Key（推荐 [DeepSeek](https://platform.deepseek.com)）
- 搜索 API Key（推荐 [博查 Bocha](https://open.bochaai.com)）

### 2. 安装

```bash
git clone https://github.com/seele430/ResearchSwarm.git
cd ResearchSwarm

python -m venv venv
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置

复制 `.env.example` 为 `.env`，填入你自己的密钥：

```env
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
BOCHA_API_KEY=your_bocha_api_key_here
```

### 4. 运行

```bash
python main.py
```

然后输入你的研究问题，例如：

```
AI Agent 的发展趋势
```
---

## 📖 Usage / 使用示例

### 示例问题

```
AI Agent 的发展趋势
```

### 输出示例

完整示例报告见 [examples/sample-report.md](examples/sample-report.md)。

节选：

> **## 七、结论**
> AI Agent 的发展趋势可概括为 **"技术框架已定、落地仍在爬坡、风险贯穿全链、B 端先行突破"**。
>
> 行业共识大于分歧，核心不确定性集中在两个问题上：
> 1. **规划模块能否在复杂场景中达到可靠阈值** —— 这决定技术可行性向工程可靠性的跨越
> 2. **商业模式能否从试点走向规模化付费** —— 这决定"有前景的技术"能否变为"有规模的市场"

**注意报告的结构化输出——它主动识别了核心不确定性，而不是简单罗列信息。**
---

## 🧠 Design Decisions / 设计决策

本项目记录了完整的工程决策过程。核心决策包括：

| # | 决策 | 核心权衡 |
|---|------|---------|
| 001 | 5 个 Agent 的职责划分 | 太少则协作不足，太多则通信复杂 |
| 002 | 共享 State 而非消息传递 | 简单、可观测，但不适合超大规模系统 |
| 003 | 并行调研（ThreadPoolExecutor） | 提速 3-5 倍，但受 API 限流影响 |
| 004 | Critic 反馈循环 + 最多 2 次重写 | 保证质量，但增加 token 消耗 |
| 005 | 结构化 JSON 输出（Planner/Critic） | 便于程序解析，但要处理 LLM 输出不稳定 |

**为什么记录决策？** 因为"做了什么"容易看到，"为什么这么做"才是工程价值的核心。

---
---

## ⚡ Performance / 性能对比

Researcher 阶段对 5 个子任务进行调研（每个任务 = 搜索 + LLM 提炼）。实测对比：

| 模式 | 实现方式 | Researcher 耗时 | 加速比 |
|------|---------|----------------|--------|
| **串行** | `ThreadPoolExecutor(max_workers=1)` | 46 秒 | 1.0x |
| **并行** | `ThreadPoolExecutor(max_workers=5)` | 23 秒 | **2.0x** |

> 测试问题：「AI Agent 的发展趋势」，5 个子任务，同一网络环境。

### 为什么加速比不是 5x？

理论上 5 个 worker 并行应该接近 5x 加速，实际只有 2x，原因：

1. **API 限流**：搜索 API 对同一 IP 有并发限制
2. **网络带宽**：5 个请求同时走一个出口，存在排队
3. **任务不均衡**：不同子任务的搜索 + LLM 提炼耗时不同，快的要等慢的

**结论**：并行不是免费的——要考虑下游服务的承载能力。

---
---

## 🛠️ Tech Stack / 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| 架构模式 | Multi-Agent · Plan-and-Execute · 反馈循环 |
| 并发 | `concurrent.futures.ThreadPoolExecutor` |
| LLM | DeepSeek API（OpenAI 兼容 SDK） |
| 搜索 | 博查 Bocha API |
| 网页解析 | requests · trafilatura · BeautifulSoup4 · lxml |
| 配置 | python-dotenv |

**说明**：
- 本项目**不依赖 LangChain / LangGraph**，Agent 编排、状态管理、反馈循环全部手写
- 与作者的另一项目 [DeepResearch](https://github.com/seele430/DeepResearch) 形成对比：一个是**单 Agent + ReAct**，一个是**多 Agent + Plan-and-Execute**

---
---

## 📁 Project Structure / 项目结构

```
ResearchSwarm/
├── main.py                     # 入口：输入问题、运行流水线、保存报告
├── agents/
│   ├── real_agents.py          # 5 个 Agent 的真实实现（LLM + 工具）
│   └── mock_agents.py          # Mock 版（Day 1 验证用，保留作参考）
├── core/
│   ├── state.py                # SwarmState：所有 Agent 共享的状态
│   ├── llm.py                  # LLM 调用封装
│   └── orchestrator.py         # 编排器：调度 Agent 执行顺序
├── tools.py                    # 工具集（搜索、网页抓取、笔记保存）
├── examples/
│   └── sample-report.md        # 示例报告
├── notes/                      # 每次运行的报告自动存档（gitignore）
├── requirements.txt
├── .env.example
├── .gitignore
├── DECISIONS.md                # 工程决策日志
└── README.md
```

---
---

## 🗺️ Roadmap / 后续计划

- [ ] **Web UI**：用 Streamlit / FastAPI 展示 Agent 实时协作过程
- [ ] **持久化记忆**：把 `SwarmState` 存入数据库，支持中断恢复
- [ ] **动态 Agent 数量**：根据问题复杂度自动决定 Planner 拆几个子任务、启几个 Researcher
- [ ] **更多工具**：接入 PDF 解析、代码执行、图表生成
- [ ] **评估体系**：用 RAGAS 等框架量化报告质量
- [ ] **Human-in-the-loop**：关键节点允许人工介入调整

---
## 📄 License

MIT

---

## 🙏 致谢

- [DeepSeek](https://platform.deepseek.com) — LLM 服务
- [博查 Bocha](https://open.bochaai.com) — 搜索 API
- [trafilatura](https://github.com/adbar/trafilatura) — 网页正文提取

---

**如果这个项目对你有帮助，欢迎 Star ⭐**