"""pytest 全局配置。

在任何项目模块被 import 之前塞入占位环境变量，保证测试：
1. 不依赖开发者本机的 .env（load_dotenv 默认不覆盖已存在的环境变量）；
2. 永远不会真的去调用 LLM / 搜索 API。
"""

import os

os.environ.setdefault("LLM_API_KEY", "test-key-not-real")
os.environ.setdefault("LLM_BASE_URL", "https://example.invalid/v1")
os.environ.setdefault("LLM_MODEL", "test-model")
os.environ.setdefault("BOCHA_API_KEY", "test-key-not-real")
