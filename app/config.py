import os

from dotenv import load_dotenv


load_dotenv()


DASHSCOPE_API_KEY = os.getenv(
    "DASHSCOPE_API_KEY"
)

DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

DASHSCOPE_CHAT_MODEL = os.getenv(
    "DASHSCOPE_CHAT_MODEL",
    "qwen3.7-plus",
)

DASHSCOPE_EMBEDDING_MODEL = os.getenv(
    "DASHSCOPE_EMBEDDING_MODEL",
    "qwen3.7-text-embedding",
)


DASHSCOPE_RERANK_MODEL = os.getenv(
    "DASHSCOPE_RERANK_MODEL",
    "qwen3.7-text-rerank",
)

if not DASHSCOPE_API_KEY:
    raise ValueError(
        "Missing DASHSCOPE_API_KEY in .env"
    )