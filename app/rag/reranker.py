from copy import deepcopy

import requests

from app.config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_RERANK_MODEL,
)


# ============================================================
# 1. Rerank API
# ============================================================

RERANK_URL = (
    "https://dashscope.aliyuncs.com/"
    "api/v1/services/rerank/"
    "text-rerank/text-rerank"
)


# ============================================================
# 2. Reranker
# ============================================================

def rerank(
    query: str,
    candidates: list[dict],
    top_n: int = 5,
) -> list[dict]:

    # --------------------------------------------------------
    # 1. 参数校验
    # --------------------------------------------------------

    query = query.strip()

    if not query:
        raise ValueError(
            "Rerank Query 不能为空"
        )

    if top_n <= 0:
        raise ValueError(
            "top_n 必须大于 0"
        )

    if not candidates:
        return []

    # --------------------------------------------------------
    # 2. top_n 不能超过 Candidate 数量
    # --------------------------------------------------------

    top_n = min(
        top_n,
        len(candidates),
    )

    # --------------------------------------------------------
    # 3. 提取 Candidate 文本
    #
    # candidates:
    #
    # [
    #     {
    #         "id": "...",
    #         "content": "...",
    #         "rrf_score": ...
    #     },
    #     ...
    # ]
    #
    # 转换为：
    #
    # documents:
    #
    # [
    #     "Chunk 1 文本",
    #     "Chunk 2 文本",
    #     ...
    # ]
    # --------------------------------------------------------

    documents = [
        candidate["content"]
        for candidate in candidates
    ]

    # --------------------------------------------------------
    # 4. HTTP Headers
    # --------------------------------------------------------

    headers = {
        "Authorization": (
            f"Bearer {DASHSCOPE_API_KEY}"
        ),
        "Content-Type": "application/json",
    }

    # --------------------------------------------------------
    # 5. 构造 Rerank Request Body
    # --------------------------------------------------------

    payload = {
        "model": DASHSCOPE_RERANK_MODEL,
        "input": {
            "query": query,
            "documents": documents,
        },
        "parameters": {
            "top_n": top_n,
        },
    }

    # --------------------------------------------------------
    # 6. 调用百炼 Rerank API
    # --------------------------------------------------------

    response = requests.post(
        RERANK_URL,
        headers=headers,
        json=payload,
        timeout=60,
    )

    # --------------------------------------------------------
    # 7. HTTP 状态检查
    #
    # 如果 API 返回：
    #
    # 400
    # 401
    # 403
    # 500
    #
    # 这里直接抛出异常。
    # --------------------------------------------------------

    response.raise_for_status()

    # --------------------------------------------------------
    # 8. JSON Response
    # --------------------------------------------------------

    response_data = response.json()

    rerank_results = (
        response_data
        .get("output", {})
        .get("results", [])
    )

    # --------------------------------------------------------
    # 9. 根据 Reranker 返回的 index
    #    找回原始 Candidate
    # --------------------------------------------------------

    results: list[dict] = []

    for item in rerank_results:

        document_index = item["index"]

        rerank_score = item[
            "relevance_score"
        ]

        # ----------------------------------------------------
        # index 指向的是：
        #
        # documents[index]
        #
        # 而 documents 与 candidates
        # 顺序完全一致。
        #
        # 所以：
        #
        # candidates[index]
        #
        # 就能找回完整的原始 Candidate。
        # ----------------------------------------------------

        candidate = deepcopy(
            candidates[document_index]
        )

        # ----------------------------------------------------
        # 保存 Reranker Score
        # ----------------------------------------------------

        candidate[
            "rerank_score"
        ] = rerank_score

        # ----------------------------------------------------
        # 为下游统一 score 接口
        #
        # Hybrid 阶段：
        # score = rrf_score
        #
        # Rerank 阶段：
        # score = rerank_score
        # ----------------------------------------------------

        candidate["score"] = (
            rerank_score
        )

        results.append(
            candidate
        )

    # --------------------------------------------------------
    # 10. 返回 Reranker 已排序结果
    # --------------------------------------------------------

    return results