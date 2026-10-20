from pathlib import Path

from app.rag.loader import load_pdf

from app.rag.chunker import (
    split_by_section,
    chunk_sections,
)

from app.rag.embeddings import (
    embed_documents,
)

from app.rag.vector_store import (
    get_qdrant_client,
    reset_collection,
    upsert_documents,
)


# ============================================================
# 1. 知识库文件路径
# ============================================================

KNOWLEDGE_PATH = Path(
    "data/knowledge/raw/"
    "industrial_robot_maintenance_manual.pdf"
)


# ============================================================
# 2. 构建 RAG 索引
# ============================================================

def build_rag_index() -> None:

    print(
        "开始构建 RAG 知识库索引..."
    )

    # ========================================================
    # 1. 加载 PDF
    # ========================================================

    pages = load_pdf(
        KNOWLEDGE_PATH
    )

    print(
        f"PDF Pages: {len(pages)}"
    )

    # ========================================================
    # 2. Section Parsing
    # ========================================================

    sections = split_by_section(
        pages
    )

    print(
        f"Sections: {len(sections)}"
    )

    # ========================================================
    # 3. Chunking
    # ========================================================

    documents = chunk_sections(
        sections
    )

    print(
        f"Chunks: {len(documents)}"
    )

    if not documents:
        raise RuntimeError(
            "没有生成任何 Chunk，停止建库"
        )

    # ========================================================
    # 4. Embedding
    # ========================================================

    print(
        "正在生成 Embedding..."
    )

    embeddings = embed_documents(
        documents
    )

    print(
        f"Embeddings: {len(embeddings)}"
    )

    # ========================================================
    # 5. 检查 Document / Embedding 数量
    # ========================================================

    if len(documents) != len(embeddings):
        raise RuntimeError(
            "Document 数量与 Embedding 数量不一致"
        )

    # ========================================================
    # 6. 创建 Qdrant Client
    # ========================================================

    client = get_qdrant_client()

    try:

        # ====================================================
        # 7. 重建 Collection
        # ====================================================

        print(
            "正在重建 Qdrant Collection..."
        )

        reset_collection(
            client
        )

        # ====================================================
        # 8. 写入 Documents + Embeddings
        # ====================================================

        inserted_count = upsert_documents(
            client=client,
            documents=documents,
            embeddings=embeddings,
        )

        # ====================================================
        # 9. 输出建库结果
        # ====================================================

        print(
            f"写入 Qdrant Points: "
            f"{inserted_count}"
        )

        print(
            "RAG 知识库索引构建完成。"
        )

    finally:

        # ====================================================
        # 10. 关闭 Qdrant Client
        # ====================================================

        client.close()


# ============================================================
# 3. Script Entry
# ============================================================

if __name__ == "__main__":
    build_rag_index()