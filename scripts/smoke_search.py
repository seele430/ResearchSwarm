"""手工冒烟脚本：真实调用一次博查搜索（需要 .env 里有 BOCHA_API_KEY）。

用法（在项目根目录）：python -m scripts.smoke_search
注意：这不是 pytest 测试（pytest.ini 的 testpaths 只收集 tests/）。
"""

from dotenv import load_dotenv

from tools import SearchError, format_search_results, web_search


def main() -> None:
    load_dotenv()
    print("=== 测试搜索 ===")
    try:
        results = web_search("AI Agent 框架", max_results=2)
    except SearchError as exc:
        print(f"搜索失败: {exc}")
    else:
        print(format_search_results(results)[:500])


if __name__ == "__main__":
    main()
