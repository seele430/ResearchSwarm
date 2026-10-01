"""用户配置：API Key / Base URL / 模型名。

- **存放位置**：`%APPDATA%\\ResearchSwarm\\config.json`（Windows 的每用户配置惯例）
- **读取优先级**：config.json > 环境变量（.env）—— 桌面版里用户在界面上填的值必须生效
- **安全约定**：Key 以明文 JSON 存放在当前用户目录（受 NTFS 用户权限保护）。
  本模块保证任何对外描述（`describe()`）都**只返回掩码**，从不回传完整 Key。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "ResearchSwarm"

# 配置键 → 环境变量名（config.json 优先）
ENV_NAMES = {
    "api_key": "LLM_API_KEY",
    "base_url": "LLM_BASE_URL",
    "model": "LLM_MODEL",
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or (Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """读取配置；文件不存在或损坏时返回空字典（绝不抛异常打断启动）。"""
    target = path or config_path()
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(values: dict[str, Any], path: Path | None = None) -> Path:
    """合并写入配置（值为 None 的键跳过，便于「只更新某个字段」）。"""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    merged = load_config(target)
    merged.update({k: v for k, v in values.items() if v is not None})
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def get_setting(name: str, default: str = "", path: Path | None = None) -> str:
    """按 config.json > 环境变量 > 默认值 的顺序取字符串配置。"""
    value = load_config(path).get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    env = os.environ.get(ENV_NAMES.get(name, ""), "")
    return env.strip() or default


def get_api_key() -> str:
    return get_setting("api_key")


def get_base_url() -> str:
    return get_setting("base_url")


def get_model() -> str:
    return get_setting("model")


def mask_secret(secret: str) -> str:
    """把密钥变成可展示的掩码（前后各留 4 位，中间固定 6 个星号）。"""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * 6}{secret[-4:]}"


def describe() -> dict[str, Any]:
    """给界面/接口用的配置描述：**只含掩码，不含明文**。"""
    key = get_api_key()
    return {
        "has_api_key": bool(key),
        "api_key_masked": mask_secret(key),
        "base_url": get_base_url(),
        "model": get_model(),
        "config_path": str(config_path()),
        "source": "config.json" if load_config().get("api_key") else ("env" if key else "none"),
    }
