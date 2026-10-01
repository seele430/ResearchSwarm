# 技术决策记录

记录「做了什么」之外的**为什么**：当时的备选方案、取舍、以及代价。
每条决策都尽量附上代码位置或测试名，便于核对是否已兑现。

| # | 决策 | 状态 |
|---|------|------|
| 001 | 5 个 Agent 的职责划分 | 已实现 |
| 002 | 共享 State 而非消息传递 | 已实现 |
| 003 | 并行调研（ThreadPoolExecutor） | 已实现 + **口径已修正** |
| 004 | Critic 反馈循环 + 最多 2 次重写 | 已实现 + **修复 off-by-one** |
| 005 | 结构化 JSON 输出 | 已实现 + **加固** |
| 006 | 失败必须显式记账 | 已实现 |
| 007 | 来源可核验：抓正文 + 确定性来源清单 | 已实现 |
| 008 | 补研回边：Analyst → Planner → Researcher | 已实现 |
| 009 | 可观测与性能测量口径 | 已实现 |
| 010 | 删除 mock_agents，改为离线 demo | 已实现 |

---

## 决策 001：5 个 Agent 的职责划分

### 背景
多 Agent 系统需要确定「几个 Agent、各自负责什么」。

### 方案对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| 3 个（Plan/Research/Write） | 简单 | 缺少质量把关 |
| **5 个（Plan/Research/Analyze/Write/Critic）** | 职责清晰、有反馈 | 通信更复杂 |
| 7+ 个 | 更细 | 过度设计 |

### 决策
采用 **5 个 Agent**：规划 → 调研 → 分析 → 写作 ⇄ 评审。

### 理由
1. 覆盖「规划-执行-分析-输出-评审」完整闭环；
2. Critic 提供质量保障，这是多 Agent 相比单 Agent 的核心优势；
3. 5 个是「职责清晰」与「通信复杂度」的平衡点。

### 后续修正
Analyst 后来被赋予**报出信息缺口**的职责（见决策 008）—— 它不再只是流水线的一环，
而是驱动回边的信号源。

---

## 决策 002：共享 State 而非消息传递

### 背景
多 Agent 通信有两种主流模式：点对点消息 vs 共享状态。

### 决策
采用**共享状态**（`SwarmState`，`core/state.py`）。

### 理由
1. 简单：不需要定义消息格式与路由规则；
2. 可观测：所有中间产物集中一处，调试、失败复盘、生成报告来源清单都直接读它；
3. 适合中小规模（5 个 Agent）。

### 已知局限与配套约束
- 规模上去（50+ Agent）时共享状态会成为瓶颈，届时应转向消息队列/事件总线；
- **共享可变状态在并发下不安全**：并发只发生在 Researcher 内部，且写回 `findings`
  被放在 `executor.map` 之后由主线程串行完成（见 `agents/real_agents.py:researcher_agent`），
  这是有意为之；将来若让多个 Agent 同时写 `state`，必须引入锁或改为消息传递。

---

## 决策 003：并行调研（ThreadPoolExecutor）

### 背景
Researcher 需要对多个子任务调研，串行耗时线性叠加。

### 方案
`ThreadPoolExecutor`，并发度由模块常量 `RESEARCH_MAX_WORKERS` 控制（默认 5）。

### 实测结果（口径已修正）

早期版本 README 里同时写着「提速 3-5 倍」和「实测 2.0x」，自相矛盾。
现在性能数字**由脚本产出**，不再手工填表：

| 模式 | 耗时 | 加速比 | 条件 |
|------|------|--------|------|
| 串联（max_workers=1） | 12.01 s | 1.00x | 离线桩，5 子任务，2 次取中位数 |
| 并联（max_workers=5） | 2.40 s | **5.00x** | 同上 |
| 并联（真实 API，历史实测） | 46 s → 23 s | **2.0x** | 真实搜索 + LLM，受网络与限流影响 |

复现：`python -m scripts.bench_research --tasks 5 --repeat 2`（离线）
或 `--live`（真实调用，消耗 token）。

### 反思
离线桩测的是**调度效率上界**。真实环境达不到 5x，原因：
1. 搜索 API 对同 IP 有并发限制；
2. 多请求共享出口带宽；
3. 子任务耗时不均，快的等慢的。

**结论**：并行不是免费的，并发度要按下游承载能力设置，而不是越大越好。

---

## 决策 004：Critic 反馈循环 + 最多 2 次重写

### 背景
Writer 一次生成的报告不保证达标，需要质量把关。

### 方案
Critic 打分（0–10）并给出改进意见，不通过则打回 Writer 重写；重写时**携带评审意见与上一版草稿**。

### 关键设计
- **评分量化**：让「质量」可衡量；
- **最多 2 次重写**：防止无限循环；
- **语义必须精确**（曾经搞错）：`MAX_REVISIONS = 2` 表示**最多重写 2 次**，
  即 Writer 最多被调用 **3** 次（初稿 + 2 次重写）。

### 已修复的缺陷（off-by-one）
原实现让 `critic_agent` **每次调用**都 `revision_count += 1`（通过时也加），
编排器又用 `>= MAX_REVISIONS` 判断 —— 实际只重写 **1** 次，与文档不符。
现改为：**Critic 只判定，计数由编排器在「决定打回」时推进**。
回归测试：`tests/test_review_loop.py::test_revision_count_advances_before_each_rewrite`
断言 `writer_calls == [0, 1, 2]`。

### 权衡
- 优点：报告质量明显提升（评审意见会进 Writer 的 prompt）；
- 代价：每次重写都是一次完整 LLM 调用，token 消耗上升 —— 现在这个成本可见（汇总表会打印 token 用量）。

---

## 决策 005：结构化 JSON 输出（Planner / Analyst / Critic）

### 背景
三个角色的输出都是结构化数据，但 LLM 的输出格式不稳定。

### 演进
1. **最初**：在 Planner 与 Critic 里各写一份 `raw.split("```")[1]` 取代码块 —— 一旦内容里
   出现 ``` 就会切错，且完全没有字段类型校验；
2. **现在**：统一收敛到 `core/jsonx.py`。

### 现在的实现
- `extract_json()`：**多候选**提取（代码块 → 整段 → 从每个 `[`/`{` 做括号配对扫描，
  正确跳过字符串与转义）；
- `parse_plan()` / `parse_critique()` / `parse_analysis()`：字段校验与容错
  （`"true"`/`"不通过"`、`"9"`、`score` 越界裁剪、`comment` 别名）；
- 失败策略由调用方决定：Planner 退回默认拆解、Critic 走 fail-open 并留痕、
  Analyst 退化为「整段当分析、无缺口」—— **分析正文不会因为格式问题丢掉**。

### 验证
`tests/test_json_parsing.py`（27 个用例），其中
`test_json_string_containing_triple_backticks` 专门针对旧实现的缺陷。

---

## 决策 006：失败必须显式记账

### 背景
早期 `web_search` 失败时**返回字符串** `"搜索失败: ..."`，而 Researcher 把它当作
搜索结果交给 LLM 提炼 —— 等于**让模型基于一句报错编出调研结论**，
而 prompt 里还写着「不要编造信息」。

### 决策
1. 工具层失败**抛异常**（`SearchError` / `FetchError`），不再用返回值表达错误；
2. 「没搜到结果」不是错误，返回空列表；搜索失败**重试 1 次 + 退避**；
3. 失败写入 `state.failures`，并作为「信息缺口」注入 Analyst / Writer 的 prompt；
4. 一条资料都没有时**不调用 LLM**，直接给出「无法进行分析」。

### 验证
`tests/test_research_failures.py`：`test_error_text_never_leaks_into_findings`、
`test_partial_failure_keeps_successful_findings`、`test_retries_once_then_succeeds`。

---

## 决策 007：来源可核验（抓正文 + 确定性来源清单）

### 背景
README 号称「深度研究」，但示例报告里 **http 链接数为 0** —— 结论无一可核验。

### 决策
1. 每个子任务对排名靠前的结果**抓正文**（trafilatura → BeautifulSoup 两级降级），
   失败则退回摘要并在 prompt 里如实标注；
2. 搜索结果**带编号**进入 prompt，要求模型用 `[编号]` 标注来源；
3. 报告末尾由**程序**追加 `## 参考来源` 清单 —— URL 直接取自搜索 API，
   不经过模型；模型已经写了则不重复追加。

### 权衡
- 抓正文增加耗时与失败面 → 用「尽力而为 + 如实降级」处理，单条失败不影响任务；
- 来源清单可能包含模型未实际引用的条目 → 这是可接受的：宁可多列，不可无出处。

### 验证
`tests/test_sources.py`（8 个用例）+ `tests/test_pipeline_offline.py` 断言报告含真实 URL。

---

## 决策 008：补研回边（Analyst → Planner → Researcher）

### 背景
原实现是 **Planner → Researcher → Analyst → Writer ⇄ Critic** 的固定流水线，
Analyst 发现的「信息缺口」没有任何去处，也没有重新调研的能力 ——
严格说那叫 prompt chaining，不叫多 Agent 协作。

### 决策
1. Analyst 输出 `{"analysis": ..., "gaps": [...]}`；
2. 若存在缺口或**调研失败**，Planner 把缺口改写成**可检索的新子任务**（不是照抄缺口原文）；
3. Researcher 只对「新增子任务 + 失败重试项」再跑一轮；
4. 随后 Analyst 复评，闭合缺口；整条回边受 `MAX_RESEARCH_ROUNDS`（默认 1）约束，避免无限循环。

### 权衡
- 收益：能自我补足信息、失败可重试，是「协作」而非「流水线」的实质；
- 代价：多一轮 LLM + 搜索调用（token 与时间上升）—— 可用 `MAX_RESEARCH_ROUNDS=0` 关掉。

### 验证
`tests/test_replan.py`（12 个用例）：触发条件、只调研新增项、轮次封顶、
失败重试后撤销失败记录、缺口与失败共享同一轮、两端 Agent 的降级行为。

---

## 决策 009：可观测与性能测量口径

### 背景
`state.py` 的注释写着「谁在什么时候做了什么」，但 `history` 里**没有时间、没有耗时、
没有 token 统计**；而 README 的卖点之一就是性能对比 —— 数据却是手工掐表填的。

### 决策
1. `HistoryEntry(agent, action, at, duration_ms)`：步骤级条目带耗时，
   `step_durations()` 按 agent 汇总；
2. `core/llm.py` 维护**线程安全**的 token 计量器（Researcher 并发调用，累加必须加锁），
   每次运行前 reset、结束后快照进 `state.usage`；
3. 性能表格由 `scripts/bench_research.py` 生成并写入 `docs/benchmark.md`，
   README 只引用它 —— **数字可复现，不再手填**。

### 验证
`tests/test_observability.py`（12 个用例）：时间戳/耗时、并发累加正确性
（8 线程 × 50 次）、无 usage 字段不误计、每次运行从零计量。

---

## 决策 010：删除 `mock_agents.py`，改为离线 demo

### 背景
`agents/mock_agents.py` 是 Day-1 验证状态机用的假实现，没有任何地方 import 它；
更糟的是它内部仍保留**修复前的 revision 计数语义**（Critic 里自增），
随着主流程演进会持续漂移 —— 一套会撒谎的平行实现比没有更危险。

### 决策
删除该文件，改为 `scripts/demo_offline.py`：只替换 LLM 客户端与搜索函数，
其余（编排、补研回边、评审循环、来源汇总、观测）**全部走真实代码**，
无需 API Key 即可演示完整流程。

### 验证
`python -m scripts.demo_offline` 输出包含两轮调研、来源清单与耗时/token 汇总。
