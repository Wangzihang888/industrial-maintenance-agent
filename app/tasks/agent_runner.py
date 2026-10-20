
from langchain_core.messages import HumanMessage

from app.agent.graph import graph
from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore


def build_task_prompt(
    device_id: str,
    risk_level: str,
    incident_id: str,
    alarm_code: str | None,
) -> str:
    """根据故障类型生成自动诊断任务。"""

    if alarm_code == "E-101":
        investigation = (
            "检查编码器通信状态，"
            "调用故障知识库工具检索 E-101 的"
            "故障原因和排查步骤。"
        )
    elif alarm_code == "E-102":
        investigation = (
            "检查伺服驱动器状态与故障子码，"
            "调用故障知识库工具检索 E-102 的"
            "故障原因和排查步骤。"
        )
    elif alarm_code == "E-103":
        investigation = (
            "查询设备状态和最近24小时的温度历史，"
            "调用故障知识库工具检索 E-103 的"
            "原因、排查步骤及安全注意事项。"
        )
    else:
        investigation = (
            "查询设备当前状态；如果存在明确故障代码，"
            "根据该代码检索知识库。"
            "没有可靠证据时不要编造故障原因或报警代码。"
        )

    return (
        "这是设备监控系统创建的自动处置任务。\n"
        f"设备编号：{device_id}\n"
        f"Incident ID：{incident_id}\n"
        f"处置类别：{risk_level}\n"
        f"Incident 报警代码：{alarm_code or '无明确报警'}\n"
        f"{investigation}\n"
        "请使用设备状态查询工具获取当前设备信息。"
        "请区分 Incident 的触发事实和设备最新状态。\n"
        "故障原因只能作为待现场核实的可能原因。"
        "不能绕过人工审批创建正式维修工单。"
    )


def run_agent_task(
    task_id: str,
    task_store: TaskStore | None = None,
) -> dict:
    """领取自动任务并执行 LangGraph。"""

    if task_store is None:
        task_store = TaskStore()

    task = task_store.get_task(task_id)

    if task is None:
        raise ValueError(f"任务不存在：{task_id}")

    if task["status"] != "pending":
        return {
            "task_id": task_id,
            "started": False,
            "status": task["status"],
        }

    # 任务必须关联真实 Incident
    incident = IncidentStore().get_incident(
        task["incident_id"]
    )

    if incident is None:
        raise ValueError("任务关联的 Incident 不存在")

    if incident["device_id"] != task["device_id"]:
        raise ValueError("任务与 Incident 的设备不一致")

    risk_level = task["risk_level"]
    incident_key = incident["incident_key"]

    # 新规则：
    # 编码器、驱动故障 -> fault
    # 温度异常 -> warning / critical
    #
    # 旧版 critical 故障任务允许继续恢复，
    # 但不将其当成温度异常解释。
    if incident_key == "temperature:overheat":
        if risk_level not in ("warning", "critical"):
            raise ValueError("温度任务等级无效")
    else:
        if risk_level not in ("fault", "critical"):
            raise ValueError("设备故障任务类别无效")

    alarm_code = incident["alarm_code"]

    prompt = build_task_prompt(
        device_id=task["device_id"],
        risk_level=risk_level,
        incident_id=task["incident_id"],
        alarm_code=alarm_code,
    )

    # 原子领取，避免重复执行
    if not task_store.claim_task(task_id):
        return {
            "task_id": task_id,
            "started": False,
            "status": "not_claimed",
        }

    config = {
        "configurable": {
            "thread_id": task["thread_id"],
        },
        "recursion_limit": 30,
    }

    initial_state = {
        "messages": [HumanMessage(content=prompt)],
        "execution_mode": "automatic",
        "task_id": task_id,
        "incident_id": task["incident_id"],
        "device_id": task["device_id"],
        "trigger_risk_level": risk_level,
    }

    try:
        graph.invoke(initial_state, config=config)

        snapshot = graph.get_state(config)
        state = snapshot.values

        interrupted = any(
            getattr(item, "interrupts", ())
            for item in snapshot.tasks
        )

        if interrupted:
            new_status = "waiting_approval"

        elif snapshot.next:
            raise RuntimeError(
                "LangGraph 尚未完成，也没有正常进入审批"
            )

        elif not state.get("notification_message"):
            raise RuntimeError("Agent 未生成预期通知")

        elif state.get("need_ticket") is True:
            raise RuntimeError(
                "需要维修申请，但没有进入人工审批"
            )

        else:
            new_status = "completed"

        # fault 与 critical 均需审批：
        # 如果本次本应进入维修申请流程，
        # 却没有暂停，则视为执行失败。
        needs_approval = (
            incident_key != "temperature:overheat"
            or risk_level == "critical"
        )

        if needs_approval and new_status != "waiting_approval":
            raise RuntimeError(
                "当前任务必须进入 HITL 人工审批"
            )

        changed = task_store.transition_task(
            task_id=task_id,
            expected_status="running",
            new_status=new_status,
        )

        if not changed:
            raise RuntimeError("任务状态更新失败")

        return {
            "task_id": task_id,
            "started": True,
            "status": new_status,
            "thread_id": task["thread_id"],
            "incident_key": incident_key,
            "risk_level": risk_level,
            "alarm_code": alarm_code,
            "notification_message": state.get(
                "notification_message"
            ),
            "ticket_status": state.get("ticket_status"),
            "ticket_request": state.get("ticket_request"),
        }

    except Exception as exc:
        task_store.transition_task(
            task_id=task_id,
            expected_status="running",
            new_status="failed",
            error=str(exc),
        )
        raise
