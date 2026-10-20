from langgraph.types import interrupt

from app.state import AgentState

# ============================================================
# 5.8 Human Approval Node
# ============================================================


def approval_node(
    state: AgentState,
) -> dict:
    """
    Human-in-the-loop 节点。


    在真正创建维修工单之前：

    1. 暂停 Workflow
    2. 等待人工审批
    3. 将审批结果写回 State


    流程：

    interrupt()

        ↓

    人工 Command(resume)

        ↓

    ticket_approved
    """



    # --------------------------------------------------------
    # 1. 获取设备信息
    # --------------------------------------------------------

    device_status = state.get(
        "device_status",
        {},
    )


    device_id = device_status.get(
        "device_id",
        "UNKNOWN",
    )



    # --------------------------------------------------------
    # 2. 获取报警信息
    # --------------------------------------------------------

    alarm_code = device_status.get(
        "current_alarm",
        "UNKNOWN",
    )



    # --------------------------------------------------------
    # 3. 获取温度分析结果
    # --------------------------------------------------------

    max_temperature = state.get(
        "max_temperature"
    )


    temperature_limit = state.get(
        "temperature_limit"
    )



    # --------------------------------------------------------
    # 4. 暂停 Workflow
    # --------------------------------------------------------

    decision = interrupt(
        {

            "type":
                "maintenance_ticket_approval",


            "message":
                (
                    "检测到设备严重温度异常，"
                    "是否批准创建维修工单？"
                ),


            "device_id":
                device_id,


            "alarm_code":
                alarm_code,


            "max_temperature":
                max_temperature,


            "temperature_limit":
                temperature_limit,

        }
    )



    # --------------------------------------------------------
    # 5. 解析人工结果
    # --------------------------------------------------------

    approved = (

        decision.get(
            "approved",
            False,
        )

        if isinstance(
            decision,
            dict,
        )

        else False

    )



    return {

    "ticket_approved":
        approved,


    "ticket_status":
        (
            "approved"
            if approved
            else "rejected"
        ),

}