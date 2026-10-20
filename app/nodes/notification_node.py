
"""
工业设备 Agent 异常通知节点。

核心原则：
1. 自动任务的触发类别来自 Agent Task
2. 当前温度来自 Agent 查询的设备状态
3. 不将触发时状态和查询时状态混为一谈
4. E-101 / E-102 不使用温度风险等级
5. 自动任务通知按 task_id 持久化去重
"""

from app.state import AgentState

from app.incidents.incident_store import IncidentStore
from app.notifications.notification_store import NotificationStore

from app.monitoring.monitoring_engine import (
    classify_temperature,
)


# ============================================================
# 1. 非温度故障的通知说明
# ============================================================

FAULT_MESSAGES = {
    "encoder:communication": (
        "检测到 E-101 编码器通信异常。"
        "监控系统曾检测到连续编码器反馈失败。"
        "建议维修人员检查连接器、拖链线缆"
        "以及编码器通信线路。"
    ),
    "servo:drive_fault": (
        "检测到 E-102 伺服驱动异常。"
        "监控系统曾检测到驱动器报告故障。"
        "建议先确认机械侧是否存在卡滞，"
        "再核对驱动器报警子码和发生轴。"
        "未确认机械安全前不得反复复位。"
    ),
}


# ============================================================
# 2. 温度通知内容
# ============================================================

def build_temperature_message(
    trigger_level: str,
    device_status: dict,
) -> str:
    """
    分开表达：
    - 本次任务的温度触发等级
    - Agent 查询到的最新温度

    不把最新温度当作触发瞬间温度。

    明确标识 E-103，便于通知识别和测试验证。
    """

    if trigger_level not in ("warning", "critical"):
        raise ValueError("不支持的温度触发类别")

    # 本次修改：
    # 温度通知明确包含 E-103 故障代码。
    message = (
        "检测到 E-103 电机过热报警。"
        f"本任务由温度 {trigger_level.upper()} "
        "事件触发。"
    )

    temperature = device_status.get("temperature")
    warning = device_status.get("temperature_warning")
    limit = device_status.get("temperature_limit")

    # 没有取得可靠的当前温度及阈值：
    # 只报告已经确认的触发类别。
    if (
        temperature is None
        or warning is None
        or limit is None
    ):
        return (
            message
            + "Agent 尚未取得完整的当前温度和阈值信息，"
            "无法判断查询时的温度状态。"
        )

    # 使用与 Monitoring Engine 相同的温度规则。
    current_level = classify_temperature(
        temperature=temperature,
        warning=warning,
        limit=limit,
    )

    message += (
        f"Agent 查询时设备温度为 {temperature}℃，"
        f"预警阈值为 {warning}℃，"
        f"安全限制值为 {limit}℃。"
    )

    if current_level == "normal":
        message += (
            "查询时温度已低于预警阈值，"
            "但仍需核实异常原因及设备恢复情况。"
        )

    elif current_level == "warning":
        message += (
            "查询时温度处于预警区间，"
            "建议持续观察温度、散热和设备负载。"
        )

    elif current_level == "critical":
        message += (
            "查询时温度已超过安全限值，"
            "建议及时安排现场检查并核对"
            "是否已有对应的 Critical 处置任务。"
        )

    return message


# ============================================================
# 3. Notification Node
# ============================================================

def notification_node(state: AgentState) -> dict:
    """
    根据业务决策生成系统通知。

    自动任务：
        查询关联 Incident，生成通知并持久化。

    非自动任务：
        生成通知内容，不写入自动任务通知表。

    不负责实际短信、邮件发送或正式工单创建。
    """

    # 1. 没有通知需求时结束
    if state.get("need_notification") is not True:
        return {}

    device_status = state.get("device_status") or {}

    device_id = (
        state.get("device_id")
        or device_status.get("device_id")
        or "UNKNOWN"
    )

    device_name = (
        device_status.get("device_name")
        or device_id
    )

    level = state.get("notification_level")

    automatic = (
        state.get("execution_mode") == "automatic"
    )

    incident_key = "temperature:overheat"
    incident_id = None
    task_id = None

    # ========================================================
    # 4. 自动任务读取关联 Incident
    # ========================================================

    if automatic:
        incident_id = state.get("incident_id")
        task_id = state.get("task_id")

        if not incident_id or not task_id:
            raise ValueError(
                "自动通知缺少 Incident ID 或 Task ID"
            )

        incident = IncidentStore().get_incident(
            incident_id
        )

        if incident is None:
            raise ValueError(
                f"找不到关联 Incident：{incident_id}"
            )

        if incident["device_id"] != device_id:
            raise ValueError(
                "任务设备与 Incident 设备不一致"
            )

        incident_key = incident["incident_key"]

        # 自动任务使用自身触发类别。
        # 不使用 Incident 后来升级的最高风险。
        level = state.get("trigger_risk_level")

        # 兼容旧版以 critical 保存的 E-101/E-102 任务。
        if incident_key in FAULT_MESSAGES:
            level = "fault"

    # ========================================================
    # 5. 生成具体通知
    # ========================================================

    prefix = f"设备 {device_name}({device_id})："

    if incident_key in FAULT_MESSAGES:
        message = (
            prefix
            + FAULT_MESSAGES[incident_key]
            + "系统已发起故障处置流程。"
        )

    elif incident_key == "temperature:overheat":
        message = (
            prefix
            + build_temperature_message(
                trigger_level=level,
                device_status=device_status,
            )
        )

    else:
        raise ValueError(
            f"不支持的通知故障类型：{incident_key}"
        )

    # ========================================================
    # 6. 自动任务通知写入 SQLite
    # ========================================================

    if automatic:
        NotificationStore().save_notification(
            task_id=task_id,
            incident_id=incident_id,
            device_id=device_id,
            notification_level=level,
            message=message,
        )

    # ========================================================
    # 7. 写回 LangGraph State
    # ========================================================

    return {
        "notification_message": message,
    }
