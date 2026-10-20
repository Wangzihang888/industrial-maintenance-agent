
from app.state import AgentState
from app.incidents.incident_store import IncidentStore
from app.tools.ticket_tool import create_maintenance_ticket


TICKET_TITLES = {
    "encoder:communication": "编码器通信异常维修申请",
    "servo:drive_fault": "伺服驱动异常维修申请",
    "temperature:overheat": "设备过温异常维修申请",
}


def ticket_request_node(state: AgentState) -> dict:
    """生成维修申请，不创建正式工单。"""

    if state.get("need_ticket") is not True:
        return {}

    device_status = state.get("device_status") or {}

    if state.get("execution_mode") == "automatic":
        incident_id = state.get("incident_id")

        if not incident_id:
            raise ValueError("自动维修申请缺少 Incident ID")

        incident = IncidentStore().get_incident(incident_id)

        if incident is None:
            raise ValueError("关联 Incident 不存在")

        device_id = incident["device_id"]
        incident_key = incident["incident_key"]
        alarm_code = incident["alarm_code"]
        risk_level = state.get("trigger_risk_level")

        if (
            state.get("device_id")
            and state["device_id"] != device_id
        ):
            raise ValueError("任务设备与 Incident 不一致")

        # 不同故障有不同的有效处置条件
        if incident_key == "temperature:overheat":
            if risk_level != "critical":
                raise ValueError(
                    "温度维修申请必须由 Critical 任务触发"
                )
        elif incident_key in (
            "encoder:communication",
            "servo:drive_fault",
        ):
            # 兼容历史 critical 故障任务，
            # 新任务统一使用 fault。
            if risk_level not in ("fault", "critical"):
                raise ValueError(
                    "设备故障维修申请需要 fault 任务"
                )
        else:
            raise ValueError(
                f"未知故障类型：{incident_key}"
            )

        title = TICKET_TITLES[incident_key]

        description = (
            f"Incident：{incident_id}\n"
            f"设备编号：{device_id}\n"
            f"故障类型：{incident_key}\n"
            f"报警代码：{alarm_code or '无明确报警'}\n"
            f"处置类别：{risk_level}\n"
            f"首次记录时间：{incident['created_at']}\n"
        )

        if incident_key == "encoder:communication":
            description += (
                "监控系统检测到连续编码器通信失败。\n"
                "请检查连接器、拖链线缆及相关通信线路。"
            )

        elif incident_key == "servo:drive_fault":
            description += (
                "监控系统检测到伺服驱动器故障状态。\n"
                "请确认机械侧安全并检查驱动器报警子码。"
            )

        else:
            description += (
                "监控系统检测到严重过温异常。\n"
                "请检查散热、负载及温度采集状态。"
            )

        description += (
            "\n以上为监控触发事实和待排查事项，"
            "最终故障原因须经现场人员确认。"
        )

        ticket_request = {
            "device_id": device_id,
            "alarm_code": alarm_code,
            "title": title,
            "description": description,
        }

    else:
        # 保留旧版非自动温度申请逻辑
        device_id = (
            device_status.get("device_id")
            or state.get("device_id")
        )

        if not device_id:
            raise ValueError("维修申请缺少设备编号")

        ticket_request = {
            "device_id": device_id,
            "alarm_code": device_status.get("current_alarm"),
            "title": "设备温度异常维修申请",
            "description": (
                f"温度状态：{state.get('temperature_status')}\n"
                f"综合最高温度：{state.get('max_temperature')}℃\n"
                f"安全限制：{state.get('temperature_limit')}℃\n"
                "请结合现场数据进行检查。"
            ),
        }

    return {
        "ticket_request": ticket_request,
        "ticket_status": "pending_approval",
    }


def create_ticket_node(state: AgentState) -> dict:
    """人工审批通过后才创建正式维修工单。"""

    if state.get("ticket_approved") is not True:
        return {
            "ticket_created": False,
            "ticket_status": "rejected",
        }

    request = state.get("ticket_request") or {}

    if not request:
        return {
            "ticket_created": False,
            "ticket_status": "missing_request",
        }

    incident_id = state.get("incident_id")

    if (
        state.get("execution_mode") == "automatic"
        and not incident_id
    ):
        return {
            "ticket_created": False,
            "ticket_status": "missing_incident_id",
        }

    result = create_maintenance_ticket.invoke({
        "device_id": request["device_id"],
        "alarm_code": request.get("alarm_code"),
        "title": request["title"],
        "description": request["description"],
        "incident_id": incident_id,
    })

    if result.get("success") is True:
        ticket = result.get("ticket", {})

        return {
            "ticket_created": True,
            "ticket_status": "created",
            "ticket_id": ticket.get("ticket_id"),
        }

    return {
        "ticket_created": False,
        "ticket_status": "failed",
    }
