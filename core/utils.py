"""通用小工具：文件名净化与路径去重。

抽出来的原因：main.py 与 tools.py 各写了一套（且只有一套做了净化），
同类逻辑分叉会让"某个入口没净化"这种事故反复出现。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# Windows 非法字符 + 控制字符
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Windows 保留设备名（不区分大小写）
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(name: str, *, max_length: int = 50, fallback: str | None = None) -> str:
    """把任意字符串净化成安全的文件名主干（不含扩展名）。

    - 替换 Windows 非法字符与路径分隔符（顺带挡掉 `../` 这类穿越）
    - 去掉结尾的点与空格（Windows 不允许）
    - 折叠连续空白、限制长度
    - 空结果走 fallback（默认时间戳），保留设备名加 `_` 前缀
    """
    cleaned = _ILLEGAL.sub("_", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if max_length > 0:
        cleaned = cleaned[:max_length].strip(" .")
    if not cleaned:
        cleaned = fallback or datetime.now().astimezone().strftime("untitled_%Y%m%d_%H%M%S")
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def unique_path(path: Path, *, max_attempts: int = 1000) -> Path:
    """目标已存在时追加 _2、_3…，避免两次运行互相覆盖。"""
    if not path.exists():
        return path
    for i in range(2, max_attempts + 1):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法为 {path} 找到可用的文件名（尝试 {max_attempts} 次）")
