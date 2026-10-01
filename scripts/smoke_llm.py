"""手工冒烟脚本：真实调用一次 LLM（需要 .env 里有 LLM_API_KEY / LLM_MODEL）。

用法（在项目根目录）：python -m scripts.smoke_llm
注意：这不是 pytest 测试（pytest.ini 的 testpaths 只收集 tests/）。
"""

from core.llm import chat


def main() -> None:
    result = chat(
        system_prompt="你是一个简洁的助手",
        user_prompt="用一句话介绍自己",
    )
    print(result)


if __name__ == "__main__":
    main()
