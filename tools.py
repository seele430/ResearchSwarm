import os
import json
from datetime import datetime
import requests
import trafilatura
from bs4 import BeautifulSoup

# ---------- 工具 1：网页搜索 ----------
def web_search(query: str, max_results: int = 3) -> str:
    """用博查 API 搜索网页"""
    try:
        url = "https://api.bochaai.com/v1/web-search"
        headers = {
            "Authorization": f"Bearer {os.getenv('BOCHA_API_KEY')}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "summary": True,
            "count": max_results,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("data", {}).get("webPages", {}).get("value", [])
        if not pages:
            return "没有找到相关结果"

        items = []
        for p in pages:
            items.append({
                "title": p.get("name"),
                "url": p.get("url"),
                "snippet": (p.get("summary") or p.get("snippet") or "")[:300],
            })
        return json.dumps(items, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"搜索失败: {e}"

# ---------- 工具 2：读取网页正文 ----------
import requests  # 移到文件顶部

def read_url(url: str) -> str:
    """抓取网页正文（三级降级策略）

    1. requests 下载 → trafilatura.extract 提取正文（首选）
    2. trafilatura 失败 → BeautifulSoup 抓 <p> 标签（兜底）
    3. 都失败 → 返回错误信息
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        html = resp.text

        # ---- 方案 1：trafilatura（首选） ----
        text = trafilatura.extract(html)
        if text and len(text.strip()) > 100:
            return text[:3000]

        # ---- 方案 2：BeautifulSoup（兜底） ----
        soup = BeautifulSoup(html, "lxml")

        # 去掉 script / style / nav / footer 等噪音
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # 抓所有 <p> 标签，按顺序拼接
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        paragraphs = [p for p in paragraphs if len(p) > 20]  # 过滤太短的
        fallback = "\n\n".join(paragraphs)

        if fallback and len(fallback.strip()) > 100:
            return f"[降级方案抓取]\n{fallback[:3000]}"

        return "抓取失败：两种方案均无法提取正文"

    except Exception as e:
        return f"抓取失败: {e}"

# ---------- 工具 3：保存笔记 ----------
def save_note(filename: str, content: str) -> str:
    """保存笔记到本地"""
    os.makedirs("notes", exist_ok=True)
    safe_name = "".join(c for c in filename if c.isalnum() or c in "-_")[:50]
    if not safe_name:
        safe_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join("notes", f"{safe_name}.md")
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