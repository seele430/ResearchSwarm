"""配置层（`core/config.py`）的测试：优先级、合并、掩码、不泄漏明文。"""

from __future__ import annotations

import json

from core import config


def test_save_and_load_round_trip(tmp_path):
    target = tmp_path / "config.json"
    config.save_config({"api_key": "sk-test-1234567890", "model": "deepseek-chat"}, path=target)
    data = config.load_config(target)
    assert data["api_key"] == "sk-test-1234567890"
    assert data["model"] == "deepseek-chat"


def test_save_merges_without_dropping_existing_keys(tmp_path):
    target = tmp_path / "config.json"
    config.save_config({"api_key": "k1"}, path=target)
    config.save_config({"model": "m1"}, path=target)
    assert config.load_config(target) == {"api_key": "k1", "model": "m1"}


def test_none_values_are_skipped(tmp_path):
    target = tmp_path / "config.json"
    config.save_config({"api_key": "k1"}, path=target)
    config.save_config({"api_key": None, "base_url": "https://x/v1"}, path=target)
    data = config.load_config(target)
    assert data["api_key"] == "k1"
    assert data["base_url"] == "https://x/v1"


def test_broken_json_falls_back_to_empty(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("{ 这不是合法 JSON", encoding="utf-8")
    assert config.load_config(target) == {}


def test_config_file_takes_priority_over_env(tmp_path, monkeypatch):
    target = tmp_path / "config.json"
    config.save_config({"api_key": "from-file"}, path=target)
    monkeypatch.setenv("LLM_API_KEY", "from-env")
    assert config.get_setting("api_key", path=target) == "from-file"


def test_env_is_used_when_config_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "from-env")
    assert config.get_setting("api_key", path=tmp_path / "none.json") == "from-env"


def test_mask_secret_never_reveals_the_middle():
    masked = config.mask_secret("sk-abcdefghijklmnop")
    assert masked.startswith("sk-a")
    assert masked.endswith("mnop")
    assert "***" in masked
    assert config.mask_secret("") == ""
    assert config.mask_secret("short") == "*****"


def test_describe_returns_only_a_mask(tmp_path, monkeypatch):
    target = tmp_path / "config.json"
    monkeypatch.setattr(config, "config_path", lambda: target)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config.save_config({"api_key": "sk-super-secret-value-1234"}, path=target)

    described = config.describe()
    assert described["has_api_key"] is True
    assert described["source"] == "config.json"
    assert "sk-super-secret-value-1234" not in json.dumps(described, ensure_ascii=False)
    assert described["api_key_masked"].startswith("sk-s")
