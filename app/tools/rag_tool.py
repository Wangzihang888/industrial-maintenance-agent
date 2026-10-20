
from typing import Any

from langchain_core.tools import tool

from app.rag.rag_retriever import RAGRetriever
from app.rag.evidence_gate import evaluate_relevance
from app.rag.evidence_validator import validate_evidence


# ============================================================
# 1. RAG Retriever 缓存
# ============================================================

_rag_retriever: RAGRetriever | None = None


# ============================================================
# 2. 获取 RAG Retriever
# ============================================================

def get_rag_retriever() -> RAGRetriever:
    """
    复用同一个 RAGRetriever，
    避免每次工具调用都重新初始化。
    """

    global _rag_retriever

    if _rag_retriever is None:
        _rag_retriever = RAGRetriever()

    return _rag_retriever


# ============================================================
# 3. 故障知识检索工具
# ============================================================

@tool
def search_fault_knowledge(
    alarm_code: str,
    query: str,
) -> dict[str, Any]:
    """
    根据报警代码和实际问题查询维修知识库。

    参数：
        alarm_code:
            故障代码，例如 E-101、E-102、E-103。

        query:
            用户实际想了解的问题，
            例如故障原因、排查步骤、维修建议。

    处理流程：
        1. 校验并标准化输入
        2. 执行 RAG 检索
        3. 根据故障代码过滤证据
        4. Relevance Gate
        5. Evidence Validator
        6. 返回经过校验的维修知识

    注意：
        只返回与当前报警代码匹配的专属章节。
        不负责判断设备风险或创建维修工单。
    """

    # ========================================================
    # 1. 标准化输入
    # ========================================================

    alarm_code = alarm_code.strip().upper()
    query = query.strip()

    if not alarm_code:
        return {
            "success": False,
            "result_type": "fault_knowledge",
            "alarm_code": alarm_code,
            "error": "empty_alarm_code",
        }

    if not query:
        return {
            "success": False,
            "result_type": "fault_knowledge",
            "alarm_code": alarm_code,
            "error": "empty_query",
        }

    # ========================================================
    # 2. 获取 RAG Retriever
    # ========================================================

    rag_retriever = get_rag_retriever()

    # ========================================================
    # 3. 执行 RAG 检索
    # ========================================================

    # 将报警代码加入检索问题。
    # 即使用户只问“应该怎么排查”，
    # 检索器也能知道对应的是哪种故障。
    retrieval_query = f"{alarm_code} {query}"

    results = rag_retriever.retrieve(
        query=retrieval_query,
        top_k=5,
        candidate_k=10,
    )

    # ========================================================
    # 4. 过滤不匹配的故障章节
    # ========================================================

    # 检索结果已有 alarm_code 元数据。
    # 例如：
    # E-101 -> 编码器通信异常
    # E-102 -> 伺服驱动异常
    # E-103 -> 电机过热报警
    #
    # 当前版本只处理单个明确报警代码。
    # 不将其他故障章节混入当前故障的核心证据。
    matched_results = [
        item
        for item in results
        if item.get("alarm_code") == alarm_code
    ]

    # ========================================================
    # 5. 无匹配证据
    # ========================================================

    if not matched_results:
        return {
            "success": False,
            "result_type": "fault_knowledge",
            "alarm_code": alarm_code,
            "query": query,
            "error": "no_retrieval_results",
        }

    # ========================================================
    # 6. Stage 1：Relevance Gate
    # ========================================================

    relevance_result = evaluate_relevance(
        results=matched_results,
    )

    if relevance_result["decision"] == "reject":
        return {
            "success": False,
            "result_type": "fault_knowledge",
            "alarm_code": alarm_code,
            "query": query,
            "error": "insufficient_evidence",
            "evidence_stage": "relevance_gate",
            "evidence_status": "REJECTED",
            "evidence_reason": relevance_result["reason"],
        }

    # ========================================================
    # 7. Stage 2：Evidence Sufficiency Validator
    # ========================================================

    validation_result = validate_evidence(
        query=query,
        results=matched_results,
    )

    # ========================================================
    # 8. Evidence 不充分
    # ========================================================

    if not validation_result["sufficient"]:
        return {
            "success": False,
            "result_type": "fault_knowledge",
            "alarm_code": alarm_code,
            "query": query,
            "error": "insufficient_evidence",
            "evidence_stage": "evidence_validator",
            "evidence_status": validation_result["status"],
            "evidence_reason": validation_result["reason"],
        }

    # ========================================================
    # 9. Evidence 充分
    # ========================================================

    return {
        "success": True,
        "result_type": "fault_knowledge",
        "alarm_code": alarm_code,
        "query": query,
        "evidence_status": validation_result["status"],
        "knowledge": matched_results,
    }
