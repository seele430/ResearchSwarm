from dotenv import load_dotenv
load_dotenv()

from tools import web_search

print("=== 测试搜索 ===")
result = web_search("AI Agent 框架", max_results=2)
print(result[:500])