
from app.tasks.task_store import TaskStore


def enqueue_monitoring_result(
    monitoring_result: dict,
    task_store: TaskStore,
) -> dict:
    """
    将单个监控异常转换成 Agent Task。

    不执行 Agent，不发送通知，不创建工单。
    """

    if monitoring_result.get("should_trigger") is not True:
        return {
            "enqueued": False,
            "reason": "no_new_action",
            "task": None,
        }

    incident_id = monitoring_result.get("incident_id")
    device_id = monitoring_result.get("device_id")
    risk_level = monitoring_result.get("risk_level")

    if not isinstance(incident_id, str) or not incident_id.strip():
        raise ValueError("缺少有效 incident_id")

    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("缺少有效 device_id")

    if risk_level not in ("warning", "critical", "fault"):
        raise ValueError("不支持的处置类别")

    task = task_store.enqueue_task(
        incident_id=incident_id,
        device_id=device_id,
        risk_level=risk_level,
    )

    return {
        "enqueued": True,
        "reason": (
            "task_created"
            if task["created"]
            else "task_already_exists"
        ),
        "task": task,
    }


def enqueue_monitoring_events(
    monitoring_result: dict,
    task_store: TaskStore,
) -> list[dict]:
    """为本次采样的每个新故障分别登记任务。"""

    results = []

    for event in monitoring_result.get("events", []):
        result = enqueue_monitoring_result(
            monitoring_result=event,
            task_store=task_store,
        )
        results.append(result)

    return results
