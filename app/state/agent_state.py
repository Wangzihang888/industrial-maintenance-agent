from typing import (
    Annotated,
    TypedDict,
)

from langchain_core.messages import (
    AnyMessage,
)

from langgraph.graph.message import (
    add_messages,
)


class AgentState(
    TypedDict,
    total=False,
):
    """
    LangGraph Agent 全局状态。

    所有 Node 通过 State
    读取和更新业务数据。

    total=False 表示：
    State 中的字段不要求
    在初始化时全部存在。

    各个 Node 可以随着 Workflow
    的执行逐步补充 State。
    """


    # =====================================================
    # 1. 基础消息
    # =====================================================

    messages: Annotated[
        list[AnyMessage],
        add_messages,
    ]


    # =====================================================
    # 2. 用户请求
    # =====================================================

    device_id: str

    alarm_code: str


    # =====================================================
    # 3. Tool 查询结果
    # =====================================================

    # Device Tool 查询结果
    device_status: dict


    # History Tool 查询结果
    temperature_records: list[dict]


    # RAG Tool 查询结果
    fault_knowledge: dict


    # =====================================================
    # 4. 温度分析结果
    # =====================================================

    # 设备预警温度
    temperature_warning: float


    # 设备安全限制温度
    temperature_limit: float


    # 当前 + 历史记录中的综合最高温度
    #
    # 如果完全没有温度数据，
    # 可能为 None。
    max_temperature: float | None


    # 是否属于严重温度异常
    #
    # 当前规则：
    # critical → True
    # 其他状态 → False
    temperature_abnormal: bool


    # 综合温度风险状态：
    #
    # normal
    # warning
    # critical
    # unknown
    temperature_status: str


    # =====================================================
    # 5. 业务动作决策
    # =====================================================

    # 是否需要通知
    need_notification: bool


    # 是否需要进入维修工单流程
    need_ticket: bool


    # 通知等级：
    #
    # warning
    # critical
    #
    # normal / unknown 时可能为 None
    notification_level: str | None


    # =====================================================
    # 6. 通知结果
    # =====================================================

    notification_message: str


    # =====================================================
    # 7. 工单申请
    # =====================================================

    # 这里只是工单申请信息，
    # 不代表正式工单已经创建。
    ticket_request: dict


    # 工单流程状态，例如：
    #
    # pending_approval
    # created
    # rejected
    # failed
    # missing_request
    ticket_status: str


    # =====================================================
    # 8. Human-in-the-loop
    # =====================================================

    # 人工是否批准创建工单
    ticket_approved: bool


    # =====================================================
    # 9. 正式工单执行结果
    # =====================================================

    # Ticket Tool 是否成功创建正式工单
    ticket_created: bool


    # 正式维修工单 ID
    #
    # 尚未创建时可能不存在或为 None。
    ticket_id: str | None

    # 自动处置任务上下文
    execution_mode: str
    task_id: str
    incident_id: str
    trigger_risk_level: str