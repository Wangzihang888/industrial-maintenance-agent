
"""
Incident 与 Agent Task 只读查询工具。

功能：
1. 查询某台设备的历史 Incident。
2. 查询指定 Incident。
3. 返回每个 Incident 关联的 Agent Task。

不会创建、更新或关闭 Incident。
"""

import json

from langchain_core.tools import tool

from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore


@tool
def query_device_incidents(
    device_id: str = "",
    incident_id: str = "",
    status: str = "all",
) -> str:
    """
    查询设备故障事件及关联的 Agent 处置任务。

    可通过 device_id 查询该设备的故障历史；
    或通过 incident_id 查询指定故障。

    Args:
        device_id: 设备编号，例如 RGV-001、RB-002。
        incident_id: 故障编号，例如 INC-XXXXXXXXXXXX。
        status: all、open 或 closed。
    """

    device_id = device_id.strip().upper()
    incident_id = incident_id.strip().upper()
    status = status.strip().lower()

    if not device_id and not incident_id:
        return json.dumps(
            {
                "success": False,
                "result_type": "incident_history",
                "error": "device_id_or_incident_id_required",
            },
            ensure_ascii=False,
        )

    if status not in ("all", "open", "closed"):
        return json.dumps(
            {
                "success": False,
                "result_type": "incident_history",
                "error": "invalid_status",
            },
            ensure_ascii=False,
        )

    incident_store = IncidentStore()
    task_store = TaskStore()

    # ========================================================
    # 1. 查询 Incident
    # ========================================================

    if incident_id:
        incident = incident_store.get_incident(
            incident_id
        )

        if incident is None:
            incidents = []

        elif device_id and (
            incident["device_id"] != device_id
        ):
            incidents = []

        elif (
            status != "all"
            and incident["status"] != status
        ):
            incidents = []

        else:
            incidents = [incident]

    else:
        incidents = incident_store.list_incidents(
            status=None if status == "all" else status,
            device_id=device_id,
            limit=20,
        )

    # ========================================================
    # 2. 关联 Agent Task
    # ========================================================

    records = []

    for incident in incidents:
        tasks = task_store.get_tasks_by_incident(
            incident["incident_id"]
        )

        records.append(
            {
                "incident": incident,
                "agent_tasks": tasks,
                "agent_task_count": len(tasks),
            }
        )

    # ========================================================
    # 3. 返回结构化查询结果
    # ========================================================

    return json.dumps(
        {
            "success": True,
            "result_type": "incident_history",
            "device_id": device_id or None,
            "incident_id": incident_id or None,
            "status_filter": status,
            "count": len(records),
            "records": records,
        },
        ensure_ascii=False,
        default=str,
    )
