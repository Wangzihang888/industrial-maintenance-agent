from langchain_core.documents import Document

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)


# ============================================================
# 1. Qdrant 配置
# ============================================================

QDRANT_PATH = "data/qdrant"

COLLECTION_NAME = (
    "industrial_maintenance_knowledge"
)

VECTOR_SIZE = 1024


# ============================================================
# 2. 创建 Qdrant Client
# ============================================================

def get_qdrant_client() -> QdrantClient:
    """
    创建并返回本地 Qdrant Client。

    Qdrant 数据会持久化保存到：
    data/qdrant
    """

    return QdrantClient(
        path=QDRANT_PATH
    )


# ============================================================
# 3. 创建 Collection
# ============================================================

def create_collection(
    client: QdrantClient,
) -> None:
    """
    创建用于存储工业运维知识的 Collection。

    当前 Embedding 模型输出 1024 维向量，
    因此 Collection 的向量维度设置为 1024。

    使用 Cosine 作为向量距离度量。
    """

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=VECTOR_SIZE,
            distance=Distance.COSINE,
        ),
    )


# ============================================================
# 4. 确保 Collection 存在
# ============================================================

def ensure_collection(
    client: QdrantClient,
) -> None:
    """
    确保 Collection 存在。

    如果 Collection 已存在：
        保留原来的 Collection 和数据。

    如果 Collection 不存在：
        创建新的 Collection。

    主要用于正常运行阶段。
    """

    if client.collection_exists(
        collection_name=COLLECTION_NAME
    ):
        return

    create_collection(client)


# ============================================================
# 5. 重置 Collection
# ============================================================

def reset_collection(
    client: QdrantClient,
) -> None:
    """
    重置整个 Collection。

    如果 Collection 已存在：
        先删除旧 Collection。

    然后：
        创建新的空 Collection。

    主要用于全量重新构建 RAG 索引。
    """

    if client.collection_exists(
        collection_name=COLLECTION_NAME
    ):
        client.delete_collection(
            collection_name=COLLECTION_NAME
        )

    create_collection(client)


# ============================================================
# 6. 将 Chunk Documents 写入 Qdrant
# ============================================================

def upsert_documents(
    client: QdrantClient,
    documents: list[Document],
    embeddings: list[list[float]],
) -> int:
    """
    将 Chunk Documents 和对应的 Embeddings
    转换成 Qdrant Points，并写入 Collection。

    documents[i] 必须对应 embeddings[i]。

    每一个 Point：

        id
            = Chunk 的确定性 chunk_id

        vector
            = Chunk 对应的 Embedding

        payload
            = Chunk 原文 + metadata

    返回：
        成功提交写入的 Point 数量。
    """

    # --------------------------------------------------------
    # 1. 检查 Document 与 Embedding 数量是否一致
    # --------------------------------------------------------

    if len(documents) != len(embeddings):
        raise ValueError(
            "Document 数量与 Embedding 数量不一致"
        )

    points: list[PointStruct] = []

    # --------------------------------------------------------
    # 2. 将 Document 与对应 Embedding 配对
    # --------------------------------------------------------

    for document, embedding in zip(
        documents,
        embeddings,
    ):

        # ----------------------------------------------------
        # 3. 检查 Embedding 维度
        # ----------------------------------------------------

        if len(embedding) != VECTOR_SIZE:
            raise ValueError(
                "Embedding 维度与 VECTOR_SIZE 不一致"
            )

        # ----------------------------------------------------
        # 4. 获取 Chunk ID
        # ----------------------------------------------------

        chunk_id = document.metadata.get(
            "chunk_id"
        )

        if not chunk_id:
            raise ValueError(
                "Document 缺少 chunk_id"
            )

        # ----------------------------------------------------
        # 5. 构造 Qdrant Payload
        # ----------------------------------------------------

        payload = {
            **document.metadata,
            "content": document.page_content,
        }

        # ----------------------------------------------------
        # 6. 构造 Qdrant Point
        # ----------------------------------------------------

        point = PointStruct(
            id=chunk_id,
            vector=embedding,
            payload=payload,
        )

        points.append(point)

    # --------------------------------------------------------
    # 7. 批量写入 Qdrant
    # --------------------------------------------------------

    if points:
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True,
        )

    # --------------------------------------------------------
    # 8. 返回写入数量
    # --------------------------------------------------------

    return len(points)