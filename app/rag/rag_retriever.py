from pathlib import Path

from app.rag.loader import load_pdf

from app.rag.chunker import (
    split_by_section,
    chunk_sections,
)

from app.rag.bm25_retriever import (
    BM25Retriever,
)

from app.rag.hybrid_retriever import (
    HybridRetriever,
)

from app.rag.reranker import (
    rerank,
)


# ============================================================
# 1. 默认知识库路径
# ============================================================

DEFAULT_KNOWLEDGE_PATH = Path(
    "data/knowledge/raw/"
    "industrial_robot_maintenance_manual.pdf"
)


# ============================================================
# 2. RAG Retriever
# ============================================================

class RAGRetriever:

    def __init__(
        self,
        knowledge_path: str | Path = (
            DEFAULT_KNOWLEDGE_PATH
        ),
    ):

        # ----------------------------------------------------
        # 1. 保存知识库路径
        # ----------------------------------------------------

        self.knowledge_path = Path(
            knowledge_path
        )

        # ----------------------------------------------------
        # 2. 加载 PDF
        # ----------------------------------------------------

        pages = load_pdf(
            self.knowledge_path
        )

        # ----------------------------------------------------
        # 3. Section Parsing
        # ----------------------------------------------------

        sections = split_by_section(
            pages
        )

        # ----------------------------------------------------
        # 4. Chunking
        # ----------------------------------------------------

        self.documents = chunk_sections(
            sections
        )

        if not self.documents:
            raise RuntimeError(
                "没有生成任何 RAG Chunk"
            )

        # ----------------------------------------------------
        # 5. 构建 BM25 Retriever
        # ----------------------------------------------------

        self.bm25_retriever = (
            BM25Retriever(
                self.documents
            )
        )

        # ----------------------------------------------------
        # 6. 构建 Hybrid Retriever
        # ----------------------------------------------------

        self.hybrid_retriever = (
            HybridRetriever(
                self.bm25_retriever
            )
        )

    # ========================================================
    # 3. 完整 RAG Retrieval
    # ========================================================

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 10,
    ) -> list[dict]:

        # ----------------------------------------------------
        # 1. 清理 Query
        # ----------------------------------------------------

        query = query.strip()

        if not query:
            raise ValueError(
                "RAG Query 不能为空"
            )

        # ----------------------------------------------------
        # 2. 参数检查
        # ----------------------------------------------------

        if top_k <= 0:
            raise ValueError(
                "top_k 必须大于 0"
            )

        if candidate_k <= 0:
            raise ValueError(
                "candidate_k 必须大于 0"
            )

        if candidate_k < top_k:
            raise ValueError(
                "candidate_k 不能小于 top_k"
            )

        # ----------------------------------------------------
        # 3. Hybrid Retrieval
        # ----------------------------------------------------

        hybrid_results = (
            self.hybrid_retriever.retrieve(
                query=query,
                top_k=candidate_k,
                candidate_k=candidate_k,
            )
        )

        # ----------------------------------------------------
        # 4. Rerank
        # ----------------------------------------------------

        reranked_results = rerank(
            query=query,
            candidates=hybrid_results,
            top_n=top_k,
        )

        # ----------------------------------------------------
        # 5. 返回最终结果
        # ----------------------------------------------------

        return reranked_results