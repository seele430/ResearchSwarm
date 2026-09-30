"""真实 LLM 版本的 Agent"""

import json
from core.state import SwarmState
from core.llm import chat


PLANNER_PROMPT = """你是一个研究任务规划专家。用户会给你一个研究问题，你需要把它拆解成 3-5 个具体的子任务。

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
        # 去掉可能的 markdown 代码块标记
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        plan = json.loads(raw)
        if not isinstance(plan, list):
            raise ValueError("返回的不是列表")

        state.plan = [str(t) for t in plan]
        state.log("Planner", f"拆解出 {len(state.plan)} 个子任务")

    except Exception as e:
        # 失败时降级：用一个默认拆解
        state.log("Planner", f"LLM 调用失败({e})，使用默认拆解")
        state.plan = [
            f"调研 {state.query} 的背景",
            f"调研 {state.query} 的现状",
            f"调研 {state.query} 的趋势",
        ]

# ============================================================
# Analyst：综合分析
# ============================================================

ANALYST_PROMPT = """你是一个研究分析师。你会收到多个子任务的调研结果，需要：

1. 综合所有信息，形成整体认识
2. 识别信息之间的矛盾或不一致（如果有）
3. 提炼关键洞察
4. 用结构化的方式输出分析

输出格式：Markdown 格式的分析文本，分点清晰。不要写"根据以上"，直接给分析内容。"""


def analyst_agent(state: SwarmState):
    """Analyst：用 LLM 综合分析"""
    state.log("Analyst", "开始分析")

    # 把所有调研结果拼成一段
    findings_text = "\n\n".join(
        f"### 子任务：{task}\n{content}"
        for task, content in state.findings.items()
    )

    user_prompt = f"""用户的原始问题：{state.query}

以下是各子任务的调研结果：

{findings_text}

请综合分析这些信息。"""

    try:
        state.analysis = chat(
            system_prompt=ANALYST_PROMPT,
            user_prompt=user_prompt,
            temperature=0.5,
        )
        state.log("Analyst", f"分析完成，共 {len(state.analysis)} 字")
    except Exception as e:
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
        state.draft = chat(
            system_prompt=WRITER_PROMPT,
            user_prompt=user_prompt,
            temperature=0.7,
        )
        state.log("Writer", f"报告完成，共 {len(state.draft)} 字")
    except Exception as e:
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
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)
        state.is_approved = bool(result.get("approved", False))
        score = result.get("score", "?")
        state.critique = f"[评分: {score}] {result.get('critique', '')}"
        state.revision_count += 1

        if state.is_approved:
            state.log("Critic", f"通过（评分 {score}）")
        else:
            state.log("Critic", f"打回重写（评分 {score}）")

    except Exception as e:
        state.log("Critic", f"LLM 调用失败({e})，默认通过")
        state.is_approved = True
        state.critique = f"[评审失败] {e}"

# ============================================================
# Researcher：并行调研（真实搜索）
# ============================================================

from concurrent.futures import ThreadPoolExecutor
from tools import web_search


RESEARCHER_PROMPT = """你是一个调研员。用户会给你一个子任务，你需要从搜索结果中提炼关键信息。

要求：
1. 从搜索结果中筛选出最相关的信息
2. 提炼关键点，形成简明的调研结论
3. 保留来源链接（如果有）
4. 输出 Markdown 格式

不要编造信息。如果搜索结果不相关，直接说明"未找到有效信息"。"""


def _research_one_task(task: str) -> tuple[str, str]:
    """调研单个子任务（供线程池调用）"""
    try:
        # 1. 搜索
        raw = web_search(task, max_results=5)

        # 2. 让 LLM 从搜索结果中提炼
        result = chat(
            system_prompt=RESEARCHER_PROMPT,
            user_prompt=f"""子任务：{task}

搜索结果：
{raw}

请提炼关键信息。""",
            temperature=0.3,
        )
        return task, result
    except Exception as e:
        return task, f"[调研失败] {e}"


def researcher_agent(state: SwarmState):
    """Researcher：并行调研所有子任务"""
    state.log("Researcher", f"开始调研 {len(state.plan)} 个子任务（并行）")

    # 用线程池并行执行（最多 5 个同时跑）
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_research_one_task, state.plan))

    for task, result in results:
        state.findings[task] = result

    state.log("Researcher", f"完成 {len(state.findings)} 项调研")