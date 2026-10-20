from copy import deepcopy

from app.rag.retriever import retrieve as dense_retrieve

from app.rag.bm25_retriever import (
    BM25Retriever,
)


# ============================================================
# 1. RRF 配置
# ============================================================

RRF_K = 60


# ============================================================
# 2. Hybrid Retriever
# ============================================================

class HybridRetriever:
    """
    混合检索器。

    同时使用：

        1. Dense Retrieval
        2. BM25 Retrieval

    然后使用 RRF：
        Reciprocal Rank Fusion

    对两个检索结果进行排名融合。
    """

    # ========================================================
    # 2.1 初始化
    # ========================================================

    def __init__(
        self,
        bm25_retriever: BM25Retriever,
    ):

        # ----------------------------------------------------
        # BM25 Retriever 已经提前建立好索引。
        #
        # Hybrid Retriever 只保存它，
        # 不在每次请求时重新创建 BM25 索引。
        # ----------------------------------------------------

        self.bm25_retriever = (
            bm25_retriever
        )

    # ========================================================
    # 2.2 执行 Hybrid Retrieval
    # ========================================================

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 10,
    ) -> list[dict]:

        # ----------------------------------------------------
        # 1. 检查 Query
        # ----------------------------------------------------

        query = query.strip()

        if not query:
            raise ValueError(
                "检索 Query 不能为空"
            )

        # ----------------------------------------------------
        # 2. 检查 top_k
        # ----------------------------------------------------

        if top_k <= 0:
            raise ValueError(
                "top_k 必须大于 0"
            )

        # ----------------------------------------------------
        # 3. 检查 candidate_k
        # ----------------------------------------------------

        if candidate_k <= 0:
            raise ValueError(
                "candidate_k 必须大于 0"
            )

        if candidate_k < top_k:
            raise ValueError(
                "candidate_k 不能小于 top_k"
            )

        # ----------------------------------------------------
        # 4. Dense Retrieval
        #
        # 这里不只取最终 top_k。
        #
        # 我们先多召回一些候选文档，
        # 给 RRF 更大的融合空间。
        # ----------------------------------------------------

        dense_results = dense_retrieve(
            query=query,
            top_k=candidate_k,
        )

        # ----------------------------------------------------
        # 5. BM25 Retrieval
        # ----------------------------------------------------

        bm25_results = (
            self.bm25_retriever.retrieve(
                query=query,
                top_k=candidate_k,
            )
        )

        # ----------------------------------------------------
        # 6. RRF Fusion
        # ----------------------------------------------------

        fused_results = self._rrf_fusion(
            dense_results=dense_results,
            bm25_results=bm25_results,
        )

        # ----------------------------------------------------
        # 7. 最终只返回 Hybrid Top-K
        # ----------------------------------------------------

        return fused_results[:top_k]

    # ========================================================
    # 2.3 RRF Fusion
    # ========================================================

    @staticmethod
    def _rrf_fusion(
        dense_results: list[dict],
        bm25_results: list[dict],
    ) -> list[dict]:

        # ----------------------------------------------------
        # fused_map：
        #
        # 使用 chunk_id 作为 Key。
        #
        # 例如：
        #
        # {
        #     "chunk-A": {...},
        #     "chunk-B": {...},
        # }
        #
        # 如果 Dense 和 BM25 找到同一个 Chunk，
        # 就会进入同一个字典项。
        # ----------------------------------------------------

        fused_map: dict[str, dict] = {}

        # ----------------------------------------------------
        # 1. 处理 Dense Results
        # ----------------------------------------------------

        for rank, result in enumerate(
            dense_results,
            start=1,
        ):

            chunk_id = result["id"]

            # ------------------------------------------------
            # 如果这个 Chunk 第一次出现，
            # 先保存一份结果。
            #
            # deepcopy：
            # 避免直接修改 Dense Retriever
            # 原始返回的 result 字典。
            # ------------------------------------------------

            if chunk_id not in fused_map:

                fused_map[chunk_id] = (
                    deepcopy(result)
                )

                # --------------------------------------------
                # 初始化 Hybrid 专用字段
                # --------------------------------------------

                fused_map[chunk_id][
                    "rrf_score"
                ] = 0.0

                fused_map[chunk_id][
                    "dense_rank"
                ] = None

                fused_map[chunk_id][
                    "bm25_rank"
                ] = None

                fused_map[chunk_id][
                    "dense_score"
                ] = None

                fused_map[chunk_id][
                    "bm25_score"
                ] = None

            # ------------------------------------------------
            # 记录 Dense 原始排名
            # ------------------------------------------------

            fused_map[chunk_id][
                "dense_rank"
            ] = rank

            # ------------------------------------------------
            # 记录 Dense 原始 Score
            #
            # 注意：
            # 保存这个 Score 只是为了：
            #
            # 调试
            # 分析
            # Evaluation
            #
            # RRF 不直接使用这个 Score。
            # ------------------------------------------------

            fused_map[chunk_id][
                "dense_score"
            ] = result["score"]

            # ------------------------------------------------
            # 添加 Dense 的 RRF Contribution
            #
            # 公式：
            #
            # 1 / (RRF_K + rank)
            # ------------------------------------------------

            fused_map[chunk_id][
                "rrf_score"
            ] += (
                1.0
                / (RRF_K + rank)
            )

        # ----------------------------------------------------
        # 2. 处理 BM25 Results
        # ----------------------------------------------------

        for rank, result in enumerate(
            bm25_results,
            start=1,
        ):

            chunk_id = result["id"]

            # ------------------------------------------------
            # 如果 BM25 找到的是一个 Dense 没找到的 Chunk，
            #
            # 那么它还不存在 fused_map 中，
            # 所以创建一个新的记录。
            # ------------------------------------------------

            if chunk_id not in fused_map:

                fused_map[chunk_id] = (
                    deepcopy(result)
                )

                fused_map[chunk_id][
                    "rrf_score"
                ] = 0.0

                fused_map[chunk_id][
                    "dense_rank"
                ] = None

                fused_map[chunk_id][
                    "bm25_rank"
                ] = None

                fused_map[chunk_id][
                    "dense_score"
                ] = None

                fused_map[chunk_id][
                    "bm25_score"
                ] = None

            # ------------------------------------------------
            # 记录 BM25 Rank
            # ------------------------------------------------

            fused_map[chunk_id][
                "bm25_rank"
            ] = rank

            # ------------------------------------------------
            # 记录 BM25 原始 Score
            # ------------------------------------------------

            fused_map[chunk_id][
                "bm25_score"
            ] = result["score"]

            # ------------------------------------------------
            # 添加 BM25 的 RRF Contribution
            # ------------------------------------------------

            fused_map[chunk_id][
                "rrf_score"
            ] += (
                1.0
                / (RRF_K + rank)
            )

        # ----------------------------------------------------
        # 3. dict → list
        # ----------------------------------------------------

        fused_results = list(
            fused_map.values()
        )

        # ----------------------------------------------------
        # 4. 根据 RRF Score 从高到低排序
        # ----------------------------------------------------

        fused_results.sort(
            key=lambda result: (
                result["rrf_score"]
            ),
            reverse=True,
        )

        # ----------------------------------------------------
        # 5. 为了统一接口：
        #
        # score = 最终 Hybrid Score
        #
        # 同时：
        #
        # dense_score
        # bm25_score
        #
        # 仍然保留下来用于调试。
        # ----------------------------------------------------

        for result in fused_results:

            result["score"] = result[
                "rrf_score"
            ]

        # ----------------------------------------------------
        # 6. 返回融合结果
        # ----------------------------------------------------

        return fused_results