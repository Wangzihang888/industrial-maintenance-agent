from typing import Literal

from app.state import AgentState


def route_after_decision(
    state: AgentState,
) -> Literal[
    "notification",
    "ticket_request",
    "end",
] | list[str]:
    """
    根据业务决策结果，
    决定后续 Workflow 需要执行哪些动作。

    无动作：
        END

    只需要通知：
        notification

    同时需要通知和工单：
        notification + ticket_request
    """

    need_notification = state.get(
        "need_notification",
        False,
    )

    need_ticket = state.get(
        "need_ticket",
        False,
    )

    if (
        need_notification is True
        and need_ticket is True
    ):
        return [
            "notification",
            "ticket_request",
        ]

    if need_notification is True:
        return "notification"

    if need_ticket is True:
        return "ticket_request"

    return "end"