import time
from typing import Any

from openai import APIConnectionError, APITimeoutError

from app.rag.rag_retriever import RAGRetriever
from app.rag.evidence_gate import evaluate_relevance
from app.rag.evidence_validator import validate_evidence


# ============================================================
# 1. Evaluation Dataset
# ============================================================

TEST_CASES = [
    # --------------------------------------------------------
    # Positive / Answerable
    # --------------------------------------------------------
    {
        "case_id": "P01",
        "category": "answerable",
        "query": "E-101 报警是什么意思，应该怎么排查？",
        "expected": "PASS",
    },
    {
        "case_id": "P02",
        "category": "answerable",
        "query": "E-102 报警的可能原因是什么？",
        "expected": "PASS",
    },
    {
        "case_id": "P03",
        "category": "answerable",
        "query": "E-103 报警的原因和维修建议是什么？",
        "expected": "PASS",
    },
    {
        "case_id": "P04",
        "category": "answerable",
        "query": "E-104 位置偏差异常应该怎么处理？",
        "expected": "PASS",
    },
    {
        "case_id": "P05",
        "category": "answerable",
        "query": "机器人电机温度过高应该怎么排查？",
        "expected": "PASS",
    },
    {
        "case_id": "P06",
        "category": "answerable",
        "query": "设备出现温度预警后应该记录哪些信息？",
        "expected": "PASS",
    },
    {
        "case_id": "P07",
        "category": "answerable",
        "query": "E-103 报警解除以后还需要做什么检查？",
        "expected": "PASS",
    },
    {
        "case_id": "P08",
        "category": "answerable",
        "query": "机器人出现连续升温趋势应该如何处理？",
        "expected": "PASS",
    },
    {
        "case_id": "P09",
        "category": "answerable",
        "query": "E-101 编码器通信异常可能由哪些原因造成？",
        "expected": "PASS",
    },
    {
        "case_id": "P10",
        "category": "answerable",
        "query": "E-104 报警发生后能不能直接修改伺服参数？",
        "expected": "PASS",
    },

    # --------------------------------------------------------
    # Easy Negative
    # --------------------------------------------------------
    {
        "case_id": "N01",
        "category": "easy_negative",
        "query": "这台机器人的市场价格是多少？",
        "expected": "REJECT",
    },
    {
        "case_id": "N02",
        "category": "easy_negative",
        "query": "机器人使用的电池型号是什么？",
        "expected": "REJECT",
    },
    {
        "case_id": "N03",
        "category": "easy_negative",
        "query": "这台机器人每年的维护成本是多少？",
        "expected": "REJECT",
    },
    {
        "case_id": "N04",
        "category": "easy_negative",
        "query": "设备制造商的客服电话是多少？",
        "expected": "REJECT",
    },

    # --------------------------------------------------------
    # Wrong / Nonexistent Alarm
    # --------------------------------------------------------
    {
        "case_id": "N05",
        "category": "wrong_alarm",
        "query": "E-105 电机过热报警应该怎么排查？",
        "expected": "REJECT",
    },
    {
        "case_id": "N06",
        "category": "wrong_alarm",
        "query": "E-105 报警并且温度持续升高时应该怎么维修？",
        "expected": "REJECT",
    },
    {
        "case_id": "N07",
        "category": "wrong_alarm",
        "query": "E-110 编码器通信故障应该怎么处理？",
        "expected": "REJECT",
    },
    {
        "case_id": "N08",
        "category": "wrong_alarm",
        "query": "E-120 伺服异常报警应该怎么复位？",
        "expected": "REJECT",
    },

    # --------------------------------------------------------
    # Missing Fact
    # --------------------------------------------------------
    {
        "case_id": "N09",
        "category": "missing_fact",
        "query": "E-103 报警后的标准停机时间是多少分钟？",
        "expected": "REJECT",
    },
    {
        "case_id": "N10",
        "category": "missing_fact",
        "query": "E-103 报警时电机最高允许温度是多少摄氏度？",
        "expected": "REJECT",
    },
    {
        "case_id": "N11",
        "category": "missing_fact",
        "query": "E-101 报警后最多允许重启多少次？",
        "expected": "REJECT",
    },
    {
        "case_id": "N12",
        "category": "missing_fact",
        "query": "E-102 故障维修后的保修期是多少天？",
        "expected": "REJECT",
    },

    # --------------------------------------------------------
    # Partial Support
    # --------------------------------------------------------
    {
        "case_id": "N13",
        "category": "partial_support",
        "query": "E-103 的原因是什么，并告诉我平均维修费用是多少？",
        "expected": "REJECT",
    },
    {
        "case_id": "N14",
        "category": "partial_support",
        "query": "E-101 应该怎么排查，并告诉我更换编码器需要多少分钟？",
        "expected": "REJECT",
    },
    {
        "case_id": "N15",
        "category": "partial_support",
        "query": "E-104 应该怎么处理，并告诉我维修后的保修期限是多少？",
        "expected": "REJECT",
    },
    {
        "case_id": "N16",
        "category": "partial_support",
        "query": "温度预警后应该记录什么信息，并告诉我设备下一次一定会在什么时候发生过温。",
        "expected": "REJECT",
    },

    # --------------------------------------------------------
    # False Premise
    # --------------------------------------------------------
    {
        "case_id": "N17",
        "category": "false_premise",
        "query": "E-103 是编码器通信故障，请告诉我应该怎么检查编码器。",
        "expected": "REJECT",
    },
    {
        "case_id": "N18",
        "category": "false_premise",
        "query": "E-101 是电机过热报警，应该怎么检查散热系统？",
        "expected": "REJECT",
    },
    {
        "case_id": "N19",
        "category": "false_premise",
        "query": "E-104 是伺服驱动器故障，应该如何更换驱动器？",
        "expected": "REJECT",
    },
    {
        "case_id": "N20",
        "category": "false_premise",
        "query": "手册要求 E-103 出现后必须立即更换电机，对吗？",
        "expected": "REJECT",
    },
]


# ============================================================
# 2. API Retry
# ============================================================

def validate_with_retry(
    query: str,
    results: list[dict[str, Any]],
    max_attempts: int = 3,
) -> dict[str, Any]:
    """
    调用 Evidence Validator。

    只对临时网络连接错误 / 超时进行有限重试。
    不把 API ERROR 当成 PASS 或 REJECT。
    """

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        try:
            return validate_evidence(
                query=query,
                results=results,
            )

        except (
            APIConnectionError,
            APITimeoutError,
        ) as exc:

            print(
                f"Validator API error "
                f"(attempt {attempt}/{max_attempts}): "
                f"{exc}"
            )

            if attempt == max_attempts:
                raise

            time.sleep(2)

    raise RuntimeError(
        "Validator retry loop exited unexpectedly."
    )


# ============================================================
# 3. Run Evaluation
# ============================================================

def run_evaluation() -> None:

    rag_retriever = RAGRetriever()

    evaluation_results = []

    print(
        "\n" + "=" * 100
    )

    print(
        "Two-stage Evidence Gate Evaluation"
    )

    print(
        f"Total Cases: {len(TEST_CASES)}"
    )

    print(
        "=" * 100
    )

    for case in TEST_CASES:

        case_id = case["case_id"]
        category = case["category"]
        query = case["query"]
        expected = case["expected"]

        print(
            "\n" + "=" * 100
        )

        print(
            f"Case: {case_id}"
        )

        print(
            f"Category: {category}"
        )

        print(
            f"Expected: {expected}"
        )

        print(
            f"Query: {query}"
        )

        # ----------------------------------------------------
        # Retrieval
        # ----------------------------------------------------

        results = rag_retriever.retrieve(
            query=query,
            top_k=5,
            candidate_k=10,
        )

        # ----------------------------------------------------
        # Stage 1: Relevance Gate
        # ----------------------------------------------------

        relevance = evaluate_relevance(
            results
        )

        top_score = relevance[
            "top_score"
        ]

        print(
            f"Top Score: {top_score:.6f}"
        )

        print(
            "Relevance Gate:",
            relevance["decision"],
        )

        validator_status = "SKIPPED"
        validator_reason = ""
        final_decision = None
        error_message = None

        # ----------------------------------------------------
        # Stage 1 directly rejects low relevance
        # ----------------------------------------------------

        if relevance["decision"] == "reject":

            final_decision = "REJECT"

        # ----------------------------------------------------
        # Stage 2: Evidence Sufficiency Validator
        # ----------------------------------------------------

        else:

            try:

                validation = validate_with_retry(
                    query=query,
                    results=results,
                )

                validator_status = validation[
                    "status"
                ]

                validator_reason = validation[
                    "reason"
                ]

                if validation[
                    "sufficient"
                ]:
                    final_decision = "PASS"
                else:
                    final_decision = "REJECT"

            except (
                APIConnectionError,
                APITimeoutError,
            ) as exc:

                final_decision = "ERROR"
                validator_status = "ERROR"
                error_message = str(exc)

        # ----------------------------------------------------
        # Compare Ground Truth
        # ----------------------------------------------------

        if final_decision == "ERROR":

            outcome = "ERROR"

        elif (
            expected == "PASS"
            and final_decision == "PASS"
        ):

            outcome = "TP"

        elif (
            expected == "REJECT"
            and final_decision == "REJECT"
        ):

            outcome = "TN"

        elif (
            expected == "REJECT"
            and final_decision == "PASS"
        ):

            outcome = "FP"

        elif (
            expected == "PASS"
            and final_decision == "REJECT"
        ):

            outcome = "FN"

        else:

            raise RuntimeError(
                "Unknown evaluation outcome."
            )

        print(
            f"Validator Status: "
            f"{validator_status}"
        )

        if validator_reason:

            print(
                f"Reason: "
                f"{validator_reason}"
            )

        print(
            f"Final Decision: "
            f"{final_decision}"
        )

        print(
            f"Outcome: "
            f"{outcome}"
        )

        # ----------------------------------------------------
        # Save Result
        # ----------------------------------------------------

        evaluation_results.append(
            {
                "case_id": case_id,
                "category": category,
                "query": query,
                "expected": expected,
                "top_score": top_score,
                "relevance_decision": (
                    relevance["decision"]
                ),
                "validator_status": (
                    validator_status
                ),
                "validator_reason": (
                    validator_reason
                ),
                "final_decision": (
                    final_decision
                ),
                "outcome": outcome,
                "error": error_message,
            }
        )

    # ========================================================
    # 4. Metrics
    # ========================================================

    tp = sum(
        result["outcome"] == "TP"
        for result in evaluation_results
    )

    tn = sum(
        result["outcome"] == "TN"
        for result in evaluation_results
    )

    fp = sum(
        result["outcome"] == "FP"
        for result in evaluation_results
    )

    fn = sum(
        result["outcome"] == "FN"
        for result in evaluation_results
    )

    errors = sum(
        result["outcome"] == "ERROR"
        for result in evaluation_results
    )

    evaluated_count = (
        tp + tn + fp + fn
    )

    if evaluated_count > 0:
        accuracy = (
            tp + tn
        ) / evaluated_count
    else:
        accuracy = 0.0

    # False Accept Rate:
    # 在所有应该 REJECT 的样本中，
    # 被错误 PASS 的比例。
    negative_count = (
        tn + fp
    )

    if negative_count > 0:
        false_accept_rate = (
            fp / negative_count
        )
    else:
        false_accept_rate = 0.0

    # False Reject Rate:
    # 在所有应该 PASS 的样本中，
    # 被错误 REJECT 的比例。
    positive_count = (
        tp + fn
    )

    if positive_count > 0:
        false_reject_rate = (
            fn / positive_count
        )
    else:
        false_reject_rate = 0.0

    # ========================================================
    # 5. Final Summary
    # ========================================================

    print(
        "\n\n" + "=" * 100
    )

    print(
        "EVALUATION SUMMARY"
    )

    print(
        "=" * 100
    )

    print(
        f"Total Cases:       "
        f"{len(TEST_CASES)}"
    )

    print(
        f"Evaluated Cases:   "
        f"{evaluated_count}"
    )

    print(
        f"Errors:            "
        f"{errors}"
    )

    print()

    print(
        f"TP: {tp}"
    )

    print(
        f"TN: {tn}"
    )

    print(
        f"FP: {fp}"
    )

    print(
        f"FN: {fn}"
    )

    print()

    print(
        f"Accuracy:          "
        f"{accuracy:.2%}"
    )

    print(
        f"False Accept Rate: "
        f"{false_accept_rate:.2%}"
    )

    print(
        f"False Reject Rate: "
        f"{false_reject_rate:.2%}"
    )

    # ========================================================
    # 6. Print Failed Cases
    # ========================================================

    failed_cases = [
        result
        for result in evaluation_results
        if result["outcome"]
        in {
            "FP",
            "FN",
            "ERROR",
        }
    ]

    print(
        "\n" + "=" * 100
    )

    print(
        "FAILED / ERROR CASES"
    )

    print(
        "=" * 100
    )

    if not failed_cases:

        print(
            "None"
        )

    else:

        for result in failed_cases:

            print()

            print(
                result["case_id"],
                result["outcome"],
            )

            print(
                "Query:",
                result["query"],
            )

            print(
                "Expected:",
                result["expected"],
            )

            print(
                "Final:",
                result[
                    "final_decision"
                ],
            )

            print(
                "Top Score:",
                result[
                    "top_score"
                ],
            )

            print(
                "Validator:",
                result[
                    "validator_status"
                ],
            )

            if result[
                "validator_reason"
            ]:

                print(
                    "Reason:",
                    result[
                        "validator_reason"
                    ],
                )

            if result["error"]:

                print(
                    "Error:",
                    result["error"],
                )


# ============================================================
# 7. Entry Point
# ============================================================

if __name__ == "__main__":
    run_evaluation()