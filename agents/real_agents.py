"""真实 LLM 版本的 Agent（Planner / Researcher / Analyst / Writer / Critic）。"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from core.jsonx import parse_analysis, parse_critique, parse_plan
from core.llm import chat
from core.state import SourceRef, SwarmState
from tools import FetchError, SearchError, SearchResult, read_url, web_search

RESEARCH_MAX_RESULTS = 5
RESEARCH_MAX_PAGES = 2  # 每个子任务真正抓正文的来源条数（其余只用摘要）
RESEARCH_MAX_WORKERS = 5  # 并行调研线程数（性能脚本会改它做串联/并联对比）
READ_URL_MAX_CHARS = 1200
RESEARCH_RETRIES = 1  # 搜索失败后的重试次数（不含首次）

SOURCE_HEADING = "## 参考来源"


@dataclass(frozen=True)
class TaskOutcome:
    """单个子任务的调研结果：要么有内容，要么有失败原因，二者互斥。"""

    task: str
    content: str = ""
    error: str = ""
    sources: tuple[SourceRef, ...] = field(default_factory=tuple)


def _gap_note(state: SwarmState) -> str:
    """把失败子任务渲染成「信息缺口」提示，供 Analyst / Writer 使用。

    失败必须显式传递下去，否则模型会把"没有资料"这件事静默忽略，
    最后交出一份看不出缺口的报告。
    """
    if not state.failures:
        return ""
    lines = "\n".join(f"- {task}：{reason}" for task, reason in state.failures.items())
    return (
        "\n\n【信息缺口】以下子任务没有拿到有效资料，"
        "你必须在输出中明确标注该维度缺失，不得凭空推测或用常识补齐：\n"
        + lines
    )


def _source_list_note(sources: list[SourceRef]) -> str:
    """给 Analyst / Writer 看的编号来源清单（URL 来自搜索 API，不经模型生成）。"""
    if not sources:
        return ""
    lines = "\n".join(f"[{i}] {s.title or s.url} — {s.url}" for i, s in enumerate(sources, 1))
    return f"\n\n参考来源（引用事实时请标注对应编号）：\n{lines}"


def _with_source_appendix(draft: str, sources: list[SourceRef]) -> str:
    """保证最终报告末尾有可核验的来源清单。

    双保险：prompt 里已经要求模型按 [编号] 标注，这里再由程序追加一份
    **确定性**清单（URL 直接取自搜索结果），模型没写也不会导致报告完全没有出处。
    """
    if not sources or SOURCE_HEADING in draft:
        return draft
    lines = "\n".join(f"- [{i}] {s.title or s.url} — {s.url}" for i, s in enumerate(sources, 1))
    return f"{draft.rstrip()}\n\n{SOURCE_HEADING}\n{lines}\n"


# ============================================================
# Planner：拆解任务 / 补研规划
# ============================================================

PLANNER_PROMPT = """你是一个研究任务规划专家。用户会给你一个研究问题，
你需要把它拆解成 3-5 个具体的子任务。

要求：
1. 每个子任务应该是独立的、可执行的调研方向
2. 子任务之间应该有逻辑递进关系（背景 → 现状 → 细节 → 趋势）
3. 只输出 JSON 数组，不要其他内容

输出格式示例：
["调研 XXX 的背景", "调研 XXX 的现状", "分析 XXX 的趋势"]

现在请拆解用户的研究问题。只输出 JSON。"""


def planner_agent(state: SwarmState):
    """Planner：用 LLM 拆解任务"""
    state.log("Planner", "开始拆解任务")

    try:
        raw = chat(
            system_prompt=PLANNER_PROMPT,
            user_prompt=state.query,
            temperature=0.3,
        )
        # 统一走 core.jsonx：多候选提取 + 类型校验（替代原来各抄一份的
        # split("```") 解析，那种写法遇到内容含 ``` 就会切错）
        state.plan = parse_plan(raw)
        state.log("Planner", f"拆解出 {len(state.plan)} 个子任务")

    except Exception as e:  # noqa: BLE001 - 有意降级：LLM/抓取失败不应中断整条流水线
        # 失败时降级：用一个默认拆解
        state.log("Planner", f"计划解析或 LLM 调用失败({e})，使用默认拆解")
        state.plan = [
            f"调研 {state.query} 的背景",
            f"调研 {state.query} 的现状",
            f"调研 {state.query} 的趋势",
        ]


PLANNER_EXTEND_PROMPT = """你是一个研究任务规划专家。第一轮调研后，分析师指出了若干信息缺口。

请针对每个缺口设计 1 个**可直接搜索**的新子任务：改写成检索式问句，不要照抄缺口原文；
并避免与已有子任务重复。

只输出 JSON 数组，不要其他内容。
输出格式示例：["补充调研 XXX 的最新数据", "调研 YYY 的失败案例"]"""


def planner_extend_agent(state: SwarmState):
    """补研规划（回边）：把 Analyst 报出的信息缺口转成新的可执行子任务。

    这是"多 Agent 协作"的实质所在：缺口由 Analyst 发现，Planner 据此改计划，
    Researcher 再跑一轮 —— 而不是一条固定的单向流水线。
    """
    gaps = list(state.gaps)
    if not gaps:
        return

    state.log("Planner", f"收到 {len(gaps)} 条信息缺口，规划补充调研")
    existing = list(state.plan)

    try:
        raw = chat(
            system_prompt=PLANNER_EXTEND_PROMPT,
            user_prompt=f"""原始研究问题：{state.query}

已有子任务：
{chr(10).join(f'- {t}' for t in existing)}

分析师指出的信息缺口：
{chr(10).join(f'- {g}' for g in gaps)}

请给出新的补研子任务，只输出 JSON 数组。""",
            temperature=0.3,
        )
        candidates = parse_plan(raw)
    except Exception as e:  # noqa: BLE001 - 有意降级：LLM/抓取失败不应中断整条流水线
        state.log("Planner", f"补研规划失败({e})，直接用缺口原文当子任务")
        candidates = [f"补充调研：{g}" for g in gaps]

    existing_set = set(existing)
    added = [t for t in candidates if t not in existing_set]
    if not added:
        added = [f"补充调研：{g}" for g in gaps if f"补充调研：{g}" not in existing_set]

    state.plan.extend(added)
    state.gaps = []
    state.log("Planner", f"新增 {len(added)} 个补研子任务")


# ============================================================
# Analyst：综合分析 + 报出信息缺口
# ============================================================

ANALYST_PROMPT = """你是一个研究分析师。你会收到多个子任务的调研结果，需要：

1. 综合所有信息，形成整体认识
2. 识别信息之间的矛盾或不一致（如果有）
3. 提炼关键洞察
4. 指出**仍然缺失、且会影响结论可靠性**的信息

输出 JSON，且只输出 JSON：
{
  "analysis": "Markdown 格式的分析正文，分点清晰；引用具体事实时用 [编号] 标注来源",
  "gaps": ["仍然缺失且影响结论的信息；没有就留空数组"]
}

gaps 只填真正影响结论的缺口，最多 3 条；不要为了凑数而提问。"""


def analyst_agent(state: SwarmState):
    """Analyst：用 LLM 综合分析，并报出信息缺口（驱动补研回边）。"""
    state.log("Analyst", "开始分析")

    # 一条资料都没拿到时不要硬编：明确报缺口，且不浪费一次 LLM 调用
    if not state.findings:
        state.analysis = "所有子任务均未获得有效资料，无法进行分析。"
        state.gaps = []
        state.log("Analyst", "无可用调研结果，跳过分析")
        return

    # 把所有调研结果拼成一段
    findings_text = "\n\n".join(
        f"### 子任务：{task}\n{content}"
        for task, content in state.findings.items()
    )

    user_prompt = f"""用户的原始问题：{state.query}

以下是各子任务的调研结果：

{findings_text}
{_gap_note(state)}{_source_list_note(state.sources)}

请综合分析这些信息，并按约定格式输出 JSON。"""

    try:
        raw = chat(
            system_prompt=ANALYST_PROMPT,
            user_prompt=user_prompt,
            temperature=0.5,
        )
        result = parse_analysis(raw)
        state.analysis = result.analysis
        state.gaps = list(result.gaps)
        state.log(
            "Analyst",
            f"分析完成，共 {len(state.analysis)} 字；报出信息缺口 {len(state.gaps)} 条",
        )
    except Exception as e:  # noqa: BLE001 - 有意降级：LLM/抓取失败不应中断整条流水线
        state.log("Analyst", f"LLM 调用失败({e})")
        state.analysis = "[分析失败]"


# ============================================================
# Writer：撰写报告
# ============================================================

WRITER_PROMPT = """你是一个报告撰写专家。你会收到研究的分析内容，需要撰写一份结构化研究报告。

要求：
1. 有清晰的章节结构（至少包含：引言、核心内容、结论）
2. 语言专业、简洁
3. 逻辑通顺
4. 关键结论要有论据支撑
5. 用 Markdown 格式
6. 引用具体事实/数据时，用 [编号] 标注它来自哪条参考来源；禁止编造 URL

直接输出报告内容，不要写"以下是我的报告"之类的话。"""


def writer_agent(state: SwarmState):
    """Writer：用 LLM 撰写报告"""
    state.log("Writer", "开始撰写报告")

    # 如果有 Critic 的评审意见，说明是重写
    is_revision = bool(state.critique and not state.is_approved)

    user_prompt = f"""用户的原始问题：{state.query}

调研计划：
{chr(10).join(f'- {t}' for t in state.plan)}

分析内容：
{state.analysis}
{_gap_note(state)}{_source_list_note(state.sources)}
"""

    # 如果有评审意见，加入
    if is_revision:
        user_prompt += f"""

上一次的评审意见（请针对性改进）：
{state.critique}

上一次的报告草稿（请在此基础上改进）：
{state.draft}
"""

    user_prompt += "\n\n请撰写研究报告。"

    try:
        draft = chat(
            system_prompt=WRITER_PROMPT,
            user_prompt=user_prompt,
            temperature=0.7,
        )
        state.draft = _with_source_appendix(draft, state.sources)
        state.log("Writer", f"报告完成，共 {len(state.draft)} 字")
    except Exception as e:  # noqa: BLE001 - 有意降级：LLM/抓取失败不应中断整条流水线
        state.log("Writer", f"LLM 调用失败({e})")
        state.draft = "[报告生成失败]"


# ============================================================
# Critic：评审报告
# ============================================================

CRITIC_PROMPT = """你是一个严格的质量评审员。你需要审查一份研究报告。

评判标准：
1. 结构是否完整（是否有引言、核心内容、结论）
2. 逻辑是否通顺
3. 是否有具体论据支撑
4. 语言是否专业

请输出 JSON 格式，且只输出 JSON：
{
  "approved": true 或 false,
  "critique": "评审意见（如果不通过，说明改进方向；如果通过，说明合格）",
  "score": 0-10 的整数
}"""


def critic_agent(state: SwarmState):
    """Critic：用 LLM 评审报告"""
    state.log("Critic", "开始评审")

    user_prompt = f"""用户的原始问题：{state.query}

待评审的报告：
{state.draft}

请评审。"""

    try:
        raw = chat(
            system_prompt=CRITIC_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
        )
        verdict = parse_critique(raw)
        state.is_approved = verdict.approved
        score = verdict.score if verdict.score is not None else "?"
        state.critique = f"[评分: {score}] {verdict.critique}"

        # 注意：这里不推进 revision_count。计数语义是「已经发生的重写次数」，
        # 由编排器在决定打回时推进；否则 MAX_REVISIONS=2 实际只会重写 1 次。
        if state.is_approved:
            state.log("Critic", f"通过（评分 {score}）")
        else:
            state.log("Critic", f"打回重写（评分 {score}）")

    except Exception as e:  # noqa: BLE001 - 有意降级：LLM/抓取失败不应中断整条流水线
        state.log("Critic", f"LLM 调用失败({e})，默认通过")
        state.is_approved = True
        state.critique = f"[评审失败] {e}"


# ============================================================
# Researcher：并行调研（真实搜索 + 正文抓取）
# ============================================================

RESEARCHER_PROMPT = """你是一个调研员。用户会给你一个子任务，
以及若干条带编号的搜索结果（含正文摘录）。

要求：
1. 从结果中筛选最相关的信息，提炼关键点
2. 保留来源链接：在每条结论后用 [编号] 标注它来自哪条结果
3. 输出 Markdown 格式
4. 如果所有结果都不相关，直接说明"未找到有效信息"

不要编造信息，不要引用没有出现在结果里的 URL。"""


def _fetch_page_bodies(results: list[SearchResult], max_pages: int):
    """抓取前 max_pages 条结果的正文（尽力而为，单条失败不影响其它条）。

    Returns:
        (url -> 正文, url -> 失败原因)
    """
    bodies: dict[str, str] = {}
    errors: dict[str, str] = {}
    for result in results[:max_pages]:
        try:
            bodies[result.url] = read_url(result.url, max_chars=READ_URL_MAX_CHARS)
        except FetchError as e:
            errors[result.url] = str(e)
        except Exception as e:  # noqa: BLE001 - 抓取是最佳努力路径，任何异常都不该中断调研
            errors[result.url] = f"未知错误: {e}"
    return bodies, errors


def _format_numbered_sources(results, bodies, errors) -> str:
    """把搜索结果格式化成带编号的块（含正文或摘要 + 抓取失败说明）。"""
    if not results:
        return "（没有搜索到结果）"
    blocks = []
    for i, r in enumerate(results, 1):
        if bodies.get(r.url):
            detail = f"正文摘录:\n{bodies[r.url]}"
        elif r.url in errors:
            detail = f"摘要: {r.snippet}\n（正文抓取失败：{errors[r.url]}）"
        else:
            detail = f"摘要: {r.snippet}"
        blocks.append(f"[{i}] {r.title}\nURL: {r.url}\n{detail}")
    return "\n\n".join(blocks)


def _research_one_task(task: str) -> TaskOutcome:
    """调研单个子任务（供线程池调用）。

    关键点：
    - 搜索/提炼失败时返回带 error 的 TaskOutcome，**绝不把错误文本当作调研结果**；
    - 抓正文是"加分项"：失败就退回摘要并在 prompt 里如实标注，任务本身照常完成。
    """
    last_error = ""
    for attempt in range(RESEARCH_RETRIES + 1):
        try:
            results = web_search(task, max_results=RESEARCH_MAX_RESULTS)
        except SearchError as e:
            last_error = str(e)
            if attempt < RESEARCH_RETRIES:
                time.sleep(1.5 * (attempt + 1))  # 简单退避，缓解限流
                continue
            return TaskOutcome(task=task, error=f"搜索失败：{last_error}")

        if not results:
            return TaskOutcome(task=task, error="搜索无结果")

        bodies, fetch_errors = _fetch_page_bodies(results, RESEARCH_MAX_PAGES)
        sources = tuple(SourceRef(title=r.title, url=r.url, task=task) for r in results)

        try:
            content = chat(
                system_prompt=RESEARCHER_PROMPT,
                user_prompt=f"""子任务：{task}

搜索结果：
{_format_numbered_sources(results, bodies, fetch_errors)}

请提炼关键信息，并用 [编号] 标注来源。""",
                temperature=0.3,
            )
        except Exception as e:  # noqa: BLE001 - 有意降级：LLM/抓取失败不应中断整条流水线
            return TaskOutcome(task=task, error=f"信息提炼失败：{e}")

        return TaskOutcome(task=task, content=content, sources=sources)

    return TaskOutcome(task=task, error=f"搜索失败：{last_error}")


def researcher_agent(state: SwarmState, tasks: list[str] | None = None):
    """Researcher：并行调研。

    Args:
        tasks: 只调研这些子任务；为空则调研 `state.plan` 全量（首轮行为）。
               补研回边会把"新增子任务 + 失败重试项"作为 tasks 传进来。
    """
    targets = list(tasks) if tasks else list(state.plan)
    if not targets:
        state.log("Researcher", "没有需要调研的子任务")
        return

    state.log("Researcher", f"开始调研 {len(targets)} 个子任务（并行）")

    # 用线程池并行执行（默认 5；性能测量脚本会调成 1 做串联对比）
    with ThreadPoolExecutor(max_workers=RESEARCH_MAX_WORKERS) as executor:
        outcomes = list(executor.map(_research_one_task, targets))

    seen_urls = {s.url for s in state.sources}
    for outcome in outcomes:
        if outcome.error:
            state.failures[outcome.task] = outcome.error
            state.log("Researcher", f"调研失败：{outcome.task}（{outcome.error}）")
            continue

        state.findings[outcome.task] = outcome.content
        state.failures.pop(outcome.task, None)  # 重试成功则撤销失败记录
        for source in outcome.sources:
            if source.url in seen_urls:
                continue
            seen_urls.add(source.url)
            state.sources.append(source)

    state.log(
        "Researcher",
        f"完成 {len(state.findings)} 项调研，{len(state.failures)} 项失败，"
        f"累计 {len(state.sources)} 条来源",
    )
