"""工具集：网页搜索 / 网页正文抓取 / 笔记保存。

约定（步骤 4 起）：

- **失败一律抛异常**（`SearchError` / `FetchError`），不再返回「搜索失败: ...」这种字符串。
  否则上层会把一段报错文本当成调研结果喂给 LLM，让它基于报错编出结论。
- **「没搜到结果」不是错误**：返回空列表，由调用方决定怎么处理。
- 搜索结果返回结构化对象（带 URL），便于后续在报告里给出可核验的来源。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests
import trafilatura
from bs4 import BeautifulSoup

from core.utils import safe_filename

BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"
SNIPPET_MAX = 300
SEARCH_TIMEOUT = 30
FETCH_TIMEOUT = 15
DEFAULT_MAX_CHARS = 3000

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class ToolError(RuntimeError):
    """工具层错误基类。"""


class SearchError(ToolError):
    """搜索失败：缺密钥 / 网络异常 / 上游返回格式不符。"""


class FetchError(ToolError):
    """网页正文抓取失败。"""


@dataclass(frozen=True)
class SearchResult:
    """单条搜索结果。"""

    title: str
    url: str
    snippet: str


# ---------- 工具 1：网页搜索 ----------
def web_search(query: str, max_results: int = 3) -> list[SearchResult]:
    """调用博查 API 搜索网页。

    Raises:
        SearchError: 缺 API Key、请求失败、响应不是合法 JSON 或格式不符。
    """
    api_key = os.getenv("BOCHA_API_KEY")
    if not api_key:
        raise SearchError("缺少 BOCHA_API_KEY，请检查 .env")

    payload: dict[str, Any] = {"query": query, "summary": True, "count": max_results}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            BOCHA_ENDPOINT, headers=headers, json=payload, timeout=SEARCH_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SearchError(f"搜索请求失败: {e}") from e

    try:
        data = resp.json()
    except ValueError as e:
        raise SearchError(f"搜索响应不是合法 JSON: {e}") from e

    pages = (data.get("data") or {}).get("webPages", {}).get("value") or []
    results: list[SearchResult] = []
    for page in pages:
        url = (page.get("url") or "").strip()
        if not url:
            continue
        results.append(
            SearchResult(
                title=(page.get("name") or "").strip(),
                url=url,
                snippet=((page.get("summary") or page.get("snippet") or "")[:SNIPPET_MAX]).strip(),
            )
        )
    return results


def format_search_results(results: list[SearchResult]) -> str:
    """格式化成给 LLM 看的文本：带编号与 URL，方便后续引用。"""
    if not results:
        return "（没有搜索到结果）"
    blocks = []
    for i, r in enumerate(results, 1):
        blocks.append(f"[{i}] {r.title}\nURL: {r.url}\n摘要: {r.snippet}")
    return "\n\n".join(blocks)


# ---------- 工具 2：读取网页正文 ----------
def read_url(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """抓取网页正文，三级降级：requests 下载 → trafilatura → BeautifulSoup。

    Raises:
        FetchError: 下载失败，或两种正文提取方案都拿不到有效内容。
    """
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        html = resp.text
    except requests.RequestException as e:
        raise FetchError(f"下载失败: {e}") from e

    # 方案 1：trafilatura（首选）
    try:
        text = trafilatura.extract(html)
    except Exception:  # noqa: BLE001 - trafilatura 内部异常不应中断整条链路
        text = None
    if text and len(text.strip()) > 100:
        return text[:max_chars]

    # 方案 2：BeautifulSoup 兜底
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    fallback = "\n\n".join(p for p in paragraphs if len(p) > 20)
    if len(fallback.strip()) > 100:
        return f"[降级方案抓取]\n{fallback[:max_chars]}"

    raise FetchError("两种正文提取方案均未获得有效内容")


# ---------- 工具 3：保存笔记 ----------
def save_note(filename: str, content: str) -> str:
    """保存笔记到本地（文件名走统一净化，避免非法字符/覆盖）。"""
    os.makedirs("notes", exist_ok=True)
    stem = safe_filename(filename, max_length=50)
    path = os.path.join("notes", f"{stem}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已保存到 {path}"


# ---------- 工具 Schema（告诉 LLM 有哪些工具可用） ----------
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索网页，获取关于某个主题的链接和摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "返回结果数量", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "读取指定 URL 的网页正文内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要读取的网页地址"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "把重要信息保存为本地笔记",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "文件名（不含扩展名）"},
                    "content": {"type": "string", "description": "要保存的内容"},
                },
                "required": ["filename", "content"],
            },
        },
    },
]

# 名字 → 函数 的映射
TOOL_MAP = {
    "web_search": web_search,
    "read_url": read_url,
    "save_note": save_note,
}
