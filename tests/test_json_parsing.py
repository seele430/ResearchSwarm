"""结构化输出解析测试（步骤 6）。

历史问题：`raw.split("```")[1]` 在「JSON 字符串里含 ```」时会切错；
`score` 是字符串、`approved` 是 "true"、`plan` 元素是对象等情况全都没有校验。
"""

import pytest

from agents import real_agents
from core.jsonx import (
    Critique,
    JsonExtractError,
    extract_json,
    parse_critique,
    parse_plan,
)
from core.state import SwarmState


class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('["a", "b"]') == ["a", "b"]

    def test_fenced_json_with_language(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fenced_json_without_language(self):
        assert extract_json("```\n[1, 2]\n```") == [1, 2]

    def test_json_wrapped_in_prose(self):
        text = '好的，这是结果：\n["任务一", "任务二"]\n希望有帮助。'
        assert extract_json(text) == ["任务一", "任务二"]

    def test_json_string_containing_triple_backticks(self):
        """回归用例：老实现 split("```")[1] 在这里会切错。"""
        text = '{"critique": "报告里 ``` 这种符号太多", "approved": false, "score": 6}'
        assert extract_json(text)["approved"] is False

    def test_brackets_inside_string_do_not_break_matching(self):
        text = '说明文字 {"critique": "含 ] 和 } 的说明", "approved": true}'
        assert extract_json(text)["approved"] is True

    def test_garbage_raises(self):
        with pytest.raises(JsonExtractError):
            extract_json("这不是 JSON，也没有括号")

    def test_empty_raises(self):
        with pytest.raises(JsonExtractError):
            extract_json("   ")


class TestParsePlan:
    def test_normal_plan(self):
        assert parse_plan('["背景", "现状", "趋势"]') == ["背景", "现状", "趋势"]

    def test_strips_whitespace_and_skips_empty(self):
        assert parse_plan('["  背景  ", "", "   "]') == ["背景"]

    def test_numbers_are_coerced_to_str(self):
        assert parse_plan("[1, 2.5]") == ["1", "2.5"]

    def test_rejects_non_list(self):
        with pytest.raises(JsonExtractError):
            parse_plan('{"task": "背景"}')

    def test_rejects_object_items(self):
        with pytest.raises(JsonExtractError):
            parse_plan('[{"name": "背景"}]')

    def test_truncates_to_max_subtasks(self):
        raw = "[" + ", ".join(f'"t{i}"' for i in range(20)) + "]"
        assert len(parse_plan(raw)) == 8

    def test_custom_cap(self):
        assert len(parse_plan('["a", "b", "c"]', max_subtasks=2)) == 2


class TestParseCritique:
    def test_normal(self):
        verdict = parse_critique('{"approved": true, "critique": "合格", "score": 9}')
        assert verdict == Critique(approved=True, critique="合格", score=9)

    def test_string_bool_and_string_score(self):
        verdict = parse_critique('{"approved": "true", "critique": "ok", "score": "7"}')
        assert verdict.approved is True
        assert verdict.score == 7

    def test_chinese_bool_words(self):
        assert parse_critique('{"approved": "不通过", "critique": "x"}').approved is False

    def test_score_is_clamped(self):
        assert parse_critique('{"approved": true, "critique": "x", "score": 99}').score == 10
        assert parse_critique('{"approved": true, "critique": "x", "score": -3}').score == 0

    def test_unparsable_score_becomes_none(self):
        assert parse_critique('{"approved": true, "critique": "x", "score": "很好"}').score is None

    def test_comment_alias(self):
        assert parse_critique('{"approved": false, "comment": "缺论据"}').critique == "缺论据"

    def test_missing_approved_raises(self):
        with pytest.raises(JsonExtractError):
            parse_critique('{"critique": "没有 approved 字段"}')

    def test_non_object_raises(self):
        with pytest.raises(JsonExtractError):
            parse_critique('["approved"]')


# ---------- Agent 层：降级行为不变 ----------


def test_planner_uses_valid_plan(monkeypatch):
    monkeypatch.setattr(real_agents, "chat", lambda **_: '```json\n["背景", "现状"]\n```')
    state = SwarmState(query="q")
    real_agents.planner_agent(state)
    assert state.plan == ["背景", "现状"]


def test_planner_falls_back_on_garbage(monkeypatch):
    monkeypatch.setattr(real_agents, "chat", lambda **_: "今天天气不错")
    state = SwarmState(query="新能源")
    real_agents.planner_agent(state)
    assert len(state.plan) == 3
    assert all("新能源" in t for t in state.plan)


def test_critic_uses_parsed_verdict(monkeypatch):
    monkeypatch.setattr(
        real_agents, "chat",
        lambda **_: '```json\n{"approved": "false", "critique": "缺论据", "score": "6"}\n```',
    )
    state = SwarmState(query="q", draft="d")
    real_agents.critic_agent(state)
    assert state.is_approved is False
    assert "6" in state.critique
    assert "缺论据" in state.critique
    assert state.revision_count == 0


def test_critic_unparsable_score_shows_placeholder(monkeypatch):
    monkeypatch.setattr(
        real_agents, "chat",
        lambda **_: '{"approved": true, "critique": "ok", "score": "很好"}',
    )
    state = SwarmState(query="q", draft="d")
    real_agents.critic_agent(state)
    assert state.is_approved is True
    assert "[评分: ?]" in state.critique
