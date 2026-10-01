"""LLM 结构化输出的解析与校验。

背景：原实现把同一段解析逻辑在 planner 与 critic 里各抄一份，
用 `raw.split("```")[1]` 取代码块 —— 一旦正文/JSON 字符串里出现 ``` 就会解析错，
且完全没有字段类型校验（`score` 是字符串、`plan` 元素是对象都照样往下走）。

这里统一成：**多候选提取 → 严格校验 → 失败抛 JsonExtractError**，
由调用方决定降级策略（Planner 退回默认拆解，Critic 走 fail-open 并留痕）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

MAX_SUBTASKS = 8

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.DOTALL | re.IGNORECASE)
_PAIRS = {"[": "]", "{": "}"}
_TRUE_WORDS = {"true", "yes", "y", "1", "是", "通过", "合格"}
_FALSE_WORDS = {"false", "no", "n", "0", "否", "不通过", "不合格"}
_SCORE_MIN, _SCORE_MAX = 0, 10


class JsonExtractError(ValueError):
    """响应里找不到合法 JSON，或字段不符合约定。"""


def _match_bracket(text: str, start: int) -> int | None:
    """从 text[start]（`[` 或 `{`）出发做括号配对，返回匹配位置；不支持则 None。

    字符串与转义要跳过，否则值里出现 `]` `}` 会误判。
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _PAIRS:
            stack.append(_PAIRS[ch])
        elif ch in "]}":
            if not stack or stack.pop() != ch:
                return None
            if not stack:
                return i
    return None


def _iter_candidates(text: str) -> Iterator[str]:
    """按「代码块内容 → 整段文本 → 每个括号起点配对」的顺序给出候选。"""
    for block in _FENCE_RE.findall(text):
        block = block.strip()
        if block:
            yield block
    stripped = text.strip()
    if stripped:
        yield stripped
    for idx, ch in enumerate(text):
        if ch in _PAIRS:
            end = _match_bracket(text, idx)
            if end is not None:
                yield text[idx : end + 1]


def extract_json(text: str) -> Any:
    """从 LLM 响应中提取第一个可解析的 JSON 值。

    Raises:
        JsonExtractError: 响应为空，或所有候选都解析失败。
    """
    if not text or not text.strip():
        raise JsonExtractError("响应为空")
    for candidate in _iter_candidates(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise JsonExtractError("响应中找不到可解析的 JSON")


def parse_plan(text: str, *, max_subtasks: int = MAX_SUBTASKS) -> list[str]:
    """解析 Planner 的子任务列表并校验。

    接受字符串/数字元素（统一转成字符串并去空白），拒绝空列表、
    非数组、以及由对象/数组组成的元素；超出上限截断。
    """
    data = extract_json(text)
    if not isinstance(data, list):
        raise JsonExtractError(f"计划应为 JSON 数组，实际是 {type(data).__name__}")

    tasks: list[str] = []
    for item in data:
        if isinstance(item, bool):  # bool 是 int 的子类，单独挡掉
            continue
        if isinstance(item, (str, int, float)):
            task = str(item).strip()
            if task:
                tasks.append(task)

    if not tasks:
        raise JsonExtractError("计划为空，或元素类型不受支持")
    return tasks[:max_subtasks]


@dataclass(frozen=True)
class Critique:
    """Critic 的评审结论。"""

    approved: bool
    critique: str
    score: int | None = None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_WORDS:
            return True
        if normalized in _FALSE_WORDS:
            return False
    raise JsonExtractError(f"approved 字段无法判定为布尔值: {value!r}")


def _as_score(value: Any) -> int | None:
    """0-10 的整数分；越界裁剪，无法解析则 None（不因打分格式问题丢结论）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(_SCORE_MIN, min(_SCORE_MAX, int(value)))
    if isinstance(value, str):
        try:
            return max(_SCORE_MIN, min(_SCORE_MAX, int(float(value.strip()))))
        except ValueError:
            return None
    return None


def parse_critique(text: str) -> Critique:
    """解析 Critic 的评审 JSON（兼容 `comment` 别名与 `"9"` 这类字符串分数）。

    Raises:
        JsonExtractError: 非对象、缺 approved、或 approved 无法判定。
    """
    data = extract_json(text)
    if not isinstance(data, dict):
        raise JsonExtractError(f"评审结果应为 JSON 对象，实际是 {type(data).__name__}")
    if "approved" not in data:
        raise JsonExtractError("评审结果缺少 approved 字段")

    raw_critique = data.get("critique", data.get("comment", ""))
    critique = raw_critique if isinstance(raw_critique, str) else str(raw_critique)
    return Critique(
        approved=_as_bool(data["approved"]),
        critique=critique.strip(),
        score=_as_score(data.get("score")),
    )


MAX_GAPS = 5


@dataclass(frozen=True)
class Analysis:
    """Analyst 的产出：分析正文 + 仍然缺失的信息（驱动补研回边）。"""

    analysis: str
    gaps: tuple[str, ...] = ()


def parse_analysis(text: str, *, max_gaps: int = MAX_GAPS) -> Analysis:
    """解析 Analyst 的 JSON 产出：`{"analysis": "...", "gaps": ["..."]}`。

    **刻意 fail-soft**：分析正文是主产物，不该因为格式问题整段丢掉。
    模型直接写 Markdown（不是 JSON）时，退化为「整段当分析、无缺口」。
    """
    stripped = (text or "").strip()
    try:
        data = extract_json(stripped)
    except JsonExtractError:
        return Analysis(analysis=stripped, gaps=())

    if not isinstance(data, dict):
        return Analysis(analysis=stripped, gaps=())

    raw_analysis = data.get("analysis", data.get("content", ""))
    analysis = raw_analysis.strip() if isinstance(raw_analysis, str) else ""
    if not analysis:
        analysis = stripped

    gaps: list[str] = []
    raw_gaps = data.get("gaps")
    if isinstance(raw_gaps, list):
        for item in raw_gaps:
            if isinstance(item, str) and item.strip():
                gaps.append(item.strip())

    return Analysis(analysis=analysis, gaps=tuple(gaps[:max_gaps]))
