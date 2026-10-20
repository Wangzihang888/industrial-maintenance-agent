
"""
验证维修手册 RAG 对不同故障代码的检索能力。

直接调用真实 RAG Tool，不调用 LangGraph。
不创建 Incident、Task 或维修工单。
"""

import json

from app.tools.rag_tool import search_fault_knowledge


TEST_CASES = [
    {
        "alarm_code": "E-101",
        "query": (
            "E-101 编码器通信异常的可能原因是什么？"
            "现场应该按什么顺序排查？"
        ),
    },
    {
        "alarm_code": "E-102",
        "query": (
            "E-102 伺服驱动异常可能由哪些原因造成？"
            "应该先检查什么？"
        ),
    },
    {
        "alarm_code": "E-103",
        "query": (
            "E-103 电机过热报警的可能原因和"
            "初步排查步骤是什么？"
        ),
    },
    {
        "alarm_code": "E-999",
        "query": (
            "E-999 是什么故障？"
            "维修手册规定了哪些排查步骤？"
        ),
    },
]


def main():
    results = {}

    for case in TEST_CASES:
        alarm_code = case["alarm_code"]
        query = case["query"]

        print("\n" + "=" * 65)
        print(f"测试故障：{alarm_code}")
        print(f"检索问题：{query}")

        # 调用真实的 LangChain Tool
        result = search_fault_knowledge.invoke({
            "alarm_code": alarm_code,
            "query": query,
        })

        results[alarm_code] = result

        print(f"success：{result.get('success')}")
        print(
            "evidence_status："
            f"{result.get('evidence_status')}"
        )
        print(f"error：{result.get('error')}")
        print(
            "evidence_reason："
            f"{result.get('evidence_reason')}"
        )

        # 成功时查看真正返回给 Agent 的知识内容
        knowledge = result.get("knowledge")

        if knowledge:
            text = json.dumps(
                knowledge,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

            # 先限制终端输出长度
            print("\n检索结果预览：")
            print(text[:3500])

        else:
            print("\n没有返回可供回答的知识内容。")

    print("\n" + "=" * 65)
    print("检索结果汇总")
    print("=" * 65)

    for alarm_code, result in results.items():
        print(
            f"{alarm_code}: "
            f"success={result.get('success')}, "
            f"error={result.get('error')}"
        )

    print("\n请结合返回的原始证据检查故障代码是否匹配。")


if __name__ == "__main__":
    main()
