
from app.rag.embeddings import embed_text

from app.rag.vector_store import (
    COLLECTION_NAME,
    get_qdrant_client,
)


def retrieve(
    query: str,
    top_k: int = 5,
) -> list[dict]:

    # ============================================================
    # 1. 清理并检查用户 Query
    # ============================================================

    query = query.strip()

    if not query:
        raise ValueError(
            "检索 Query 不能为空"
        )

    if top_k <= 0:
        raise ValueError(
            "top_k 必须大于 0"
        )

    # ============================================================
    # 2. 将用户 Query 转换成向量
    # ============================================================

    query_vector = embed_text(
        query
    )

    # ============================================================
    # 3. 连接本地 Qdrant
    # ============================================================

    client = get_qdrant_client()

    try:

        # ========================================================
        # 4. 使用 Query Vector 进行向量检索
        # ========================================================

        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        # ========================================================
        # 5. 创建列表，保存最终检索结果
        # ========================================================

        results: list[dict] = []

        # ========================================================
        # 6. 将 Qdrant 返回的 ScoredPoint
        #    转换成我们自己的统一数据结构
        # ========================================================

        for point in response.points:

            payload = point.payload or {}

            result = {
                "id": str(point.id),
                "score": point.score,
                "content": payload.get(
                    "content",
                    "",
                ),
                "source": payload.get(
                    "source"
                ),
                "section_number": payload.get(
                    "section_number"
                ),
                "section_title": payload.get(
                    "section_title"
                ),
                "page_start": payload.get(
                    "page_start"
                ),
                "page_end": payload.get(
                    "page_end"
                ),
                "alarm_code": payload.get(
                    "alarm_code"
                ),
                "chunk_index": payload.get(
                    "chunk_index"
                ),
            }

            results.append(result)

        # ========================================================
        # 7. 返回 Top-K 检索结果
        # ========================================================

        return results

    finally:

        # ========================================================
        # 8. 无论检索成功还是发生异常，都关闭 Qdrant Client
        # ========================================================

        client.close()
