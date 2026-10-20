from typing import Literal

from app.state import AgentState


# ============================================================
# Approval Router
# ============================================================


def route_after_approval(
    state: AgentState,
) -> Literal[
    "create_ticket",
    "end",
]:
    """
    根据人工审批结果，
    决定是否允许 Workflow
    进入真正的工单创建节点。

    approved=True
        ↓
    create_ticket

    approved=False
        ↓
    END
    """


    # --------------------------------------------------------
    # 1. 获取审批结果
    # --------------------------------------------------------

    ticket_approved = state.get(
        "ticket_approved",
        False,
    )


    # --------------------------------------------------------
    # 2. 审批通过
    # --------------------------------------------------------

    if ticket_approved is True:

        return "create_ticket"


    # --------------------------------------------------------
    # 3. 未审批 / 拒绝
    # --------------------------------------------------------

    return "end"