from core.llm import chat

result = chat(
    system_prompt="你是一个简洁的助手",
    user_prompt="用一句话介绍自己",
)
print(result)