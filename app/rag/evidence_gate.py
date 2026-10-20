from typing import Any


# ============================================================
# 1. 默认 Relevance Threshold
# ============================================================

DEFAULT_RELEVANCE_THRESHOLD = 0.5


# ============================================================
# 2. Relevance Gate
# ============================================================

def evaluate_relevance(
    results: list[dict[str, Any]],
    threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
) -> dict[str, Any]:

    # --------------------------------------------------------
    # 1. 检查 threshold
    # --------------------------------------------------------

    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            "Relevance threshold 必须位于 0 到 1 之间"
        )

    # --------------------------------------------------------
    # 2. 没有任何 Evidence
    # --------------------------------------------------------

    if not results:
        return {
            "decision": "reject",
            "top_score": 0.0,
            "threshold": threshold,
            "reason": "no_evidence",
        }

    # --------------------------------------------------------
    # 3. 获取 Top-1 Evidence
    # --------------------------------------------------------

    top_result = results[0]

    top_score = float(
        top_result.get(
            "rerank_score",
            0.0,
        )
    )

    # --------------------------------------------------------
    # 4. 明显低相关 → 直接拒绝
    # --------------------------------------------------------

    if top_score < threshold:
        return {
            "decision": "reject",
            "top_score": top_score,
            "threshold": threshold,
            "reason": "low_relevance",
        }

    # --------------------------------------------------------
    # 5. 有相关性 → 进入 Evidence Validator
    # --------------------------------------------------------

    return {
        "decision": "need_validation",
        "top_score": top_score,
        "threshold": threshold,
        "reason": "relevance_passed",
    }