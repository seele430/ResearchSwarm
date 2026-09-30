"""统一的 LLM 调用封装"""

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)
_MODEL = os.getenv("LLM_MODEL")


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """单轮对话，返回文本"""
    resp = _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content