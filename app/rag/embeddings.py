from openai import OpenAI
from langchain_core.documents import Document

from app.config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_EMBEDDING_MODEL,
)


client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
)


def embed_text(
    text: str,
) -> list[float]:

    embeddings = embed_texts(
        [text]
    )

    return embeddings[0]


def embed_texts(
    texts: list[str],
) -> list[list[float]]:

    # ============================================================
    # 1. 检查输入列表
    # ============================================================

    if not texts:
        return []

    # ============================================================
    # 2. 清理每一条文本
    # ============================================================

    cleaned_texts: list[str] = []

    for text in texts:

        cleaned_text = text.strip()

        if not cleaned_text:
            raise ValueError(
                "Embedding 文本不能为空"
            )

        cleaned_texts.append(
            cleaned_text
        )

    # ============================================================
    # 3. 一次发送多条文本
    # ============================================================

    response = client.embeddings.create(
        model=DASHSCOPE_EMBEDDING_MODEL,
        input=cleaned_texts,
    )

    # ============================================================
    # 4. 从 response.data 中取出所有向量
    # ============================================================

    embeddings = [
        item.embedding
        for item in response.data
    ]

    # ============================================================
    # 5. 返回所有向量
    # ============================================================

    return embeddings


def embed_documents(
    documents: list[Document],
    batch_size: int = 16,
) -> list[list[float]]:

    # ============================================================
    # 1. 检查 batch_size
    # ============================================================

    if batch_size <= 0:
        raise ValueError(
            "batch_size 必须大于 0"
        )

    # ============================================================
    # 2. 没有 Document 时直接返回
    # ============================================================

    if not documents:
        return []

    # ============================================================
    # 3. 保存最终所有向量
    # ============================================================

    all_embeddings: list[list[float]] = []

    # ============================================================
    # 4. 按 batch_size 分批处理 Documents
    # ============================================================

    for start in range(
        0,
        len(documents),
        batch_size,
    ):

        end = start + batch_size

        batch_documents = documents[
            start:end
        ]

        # ========================================================
        # 5. 从当前这一批 Document 中提取 page_content
        # ========================================================

        batch_texts = [
            document.page_content
            for document in batch_documents
        ]

        # ========================================================
        # 6. 当前 Batch 批量 Embedding
        # ========================================================

        batch_embeddings = embed_texts(
            batch_texts
        )

        # ========================================================
        # 7. 检查数量是否一致
        # ========================================================

        if (
            len(batch_embeddings)
            != len(batch_documents)
        ):
            raise RuntimeError(
                "Embedding 返回数量与 Document 数量不一致"
            )

        # ========================================================
        # 8. 将当前 Batch 的结果加入总结果
        # ========================================================

        all_embeddings.extend(
            batch_embeddings
        )

    # ============================================================
    # 9. 返回所有 Document 对应的向量
    # ============================================================

    return all_embeddings