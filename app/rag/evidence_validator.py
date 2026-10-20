import json
from typing import Any

from openai import OpenAI

from app.config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_CHAT_MODEL,
)


# ============================================================
# 1. 创建 LLM Client
# ============================================================

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
)


# ============================================================
# 2. 合法 Evidence 状态
# ============================================================

VALID_STATUSES = {
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "UNSUPPORTED",
    "CONTRADICTED",
}


# ============================================================
# 3. 构建 Evidence Context
# ============================================================

def build_evidence_context(
    results: list[dict[str, Any]],
) -> str:

    evidence_blocks = []

    for rank, result in enumerate(
        results,
        start=1,
    ):

        section_number = result.get(
            "section_number"
        )

        section_title = result.get(
            "section_title"
        )

        content = result.get(
            "content",
            "",
        )

        evidence_block = (
            f"[Evidence {rank}]\n"
            f"Section: "
            f"{section_number} "
            f"{section_title}\n"
            f"Content:\n"
            f"{content}"
        )

        evidence_blocks.append(
            evidence_block
        )

    return "\n\n".join(
        evidence_blocks
    )


# ============================================================
# 4. Evidence Sufficiency Validator
# ============================================================

def validate_evidence(
    query: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:

    query = query.strip()

    if not query:
        raise ValueError(
            "Evidence Validator Query 不能为空"
        )

    if not results:
        return {
            "status": "UNSUPPORTED",
            "sufficient": False,
            "reason": "No evidence was provided.",
        }

    evidence_context = (
        build_evidence_context(
            results
        )
    )

    system_prompt = """
你是一个严格的 Evidence Sufficiency Validator。

你的任务不是回答用户问题，而是判断提供的 Evidence
是否足以在不引入外部知识的情况下，对用户的 Query
作出实质性且有依据的回答。

你只能依据提供的 Evidence 进行判断，
不能使用外部知识，不能补充 Evidence 中不存在的信息。

请严格区分以下四种状态：

SUPPORTED:
Evidence 足以支持 Query 所要求的全部关键要求，
能够基于 Evidence 对 Query 作出实质性回答。

PARTIALLY_SUPPORTED:
对于包含多个独立关键要求的 Query，
Evidence 至少支持其中一个要求，
但还有至少一个关键要求缺少支持。

UNSUPPORTED:
Evidence 与 Query 可能相关，
但没有提供足以回答 Query 核心要求的信息。

CONTRADICTED:
Query 中存在关键事实或前提，
与 Evidence 明确冲突。

判断规则：

1. 首先识别 Query 中实际提出的关键要求。
   不要自行增加 Query 没有要求的条件。

2. 如果 Query 包含多个独立关键要求，
   每个关键要求都必须得到 Evidence 支持，
   才能判定为 SUPPORTED。

3. “Evidence 足够支持回答”不等于
   “Evidence 必须穷尽所有可能的信息”。

   如果 Query 只是询问“有什么原因”“应该检查什么”
   “应该如何处理”等开放式问题，
   Evidence 已经提供了能够直接回答该问题的明确原因、
   检查项或处理措施，则可以判定为 SUPPORTED。

   除非 Query 明确要求“全部”“完整”“所有”
   “唯一”“精确”等，否则不得因为 Evidence
   没有提供穷尽性清单而降低为 PARTIALLY_SUPPORTED。

4. 不得因为 Evidence 与 Query 主题相关，
   就判定为 SUPPORTED。
   Evidence 必须实际包含回答 Query 核心要求的信息。

5. 不得根据常识、经验或外部知识
   补充 Evidence 中没有的信息。

6. 如果 Query 要求具体数字、时间、价格、
   次数、型号、期限或预测，
   Evidence 必须明确提供对应信息。

7. 如果 Query 中的关键前提
   与 Evidence 明确冲突，
   判定为 CONTRADICTED。

8. 如果复合 Query 的一个独立要求有证据，
   另一个独立要求没有证据，
   必须判定为 PARTIALLY_SUPPORTED，
   不得因为其中一部分高度相关而判定为 SUPPORTED。

只返回 JSON，不要返回 Markdown，
不要回答用户原始问题。

JSON 格式必须为：

{
    "status": "SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED",
    "reason": "简洁说明判断依据"
}
""".strip()

    user_prompt = f"""
Query:
{query}

Evidence:
{evidence_context}
""".strip()

    response = client.chat.completions.create(
        model=DASHSCOPE_CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0,
    )

    content = (
        response
        .choices[0]
        .message
        .content
    )

    if not content:
        raise RuntimeError(
            "Evidence Validator 返回空内容"
        )

    try:
        decision = json.loads(
            content
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Evidence Validator 未返回合法 JSON"
        ) from exc

    status = decision.get(
        "status"
    )

    reason = decision.get(
        "reason",
        "",
    )

    if status not in VALID_STATUSES:
        raise RuntimeError(
            f"未知 Evidence Status: {status}"
        )

    sufficient = (
        status == "SUPPORTED"
    )

    return {
        "status": status,
        "sufficient": sufficient,
        "reason": reason,
    }