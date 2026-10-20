
"""
企业设备智能运维系统：只读业务 API。

职责：
1. 查询设备最新运行状态
2. 查询设备温度历史
3. 查询 Incident 详情
4. 查询 Agent 任务
5. 查询某 Incident 的所有 Agent 任务

本文件不执行审批，也不修改业务状态。
"""

from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from app.monitoring.device_config import load_device_config
from app.monitoring.device_state_store import DeviceStateStore
from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore


router = APIRouter(
    prefix="/api",
    tags=["Operations"],
)


# ============================================================
# 1. 数据存储依赖
# ============================================================

def get_device_store() -> DeviceStateStore:
    return DeviceStateStore()


def get_incident_store() -> IncidentStore:
    return IncidentStore()


def get_task_store() -> TaskStore:
    return TaskStore()


# ============================================================
# 2. 查询设备最新状态
# ============================================================

@router.get("/devices/{device_id}")
def read_device(
    device_id: str,
    store: DeviceStateStore = Depends(get_device_store),
):
    device_id = device_id.strip().upper()

    try:
        config = load_device_config(device_id)

    except (ValueError, KeyError):
        raise HTTPException(
            status_code=404,
            detail="device_not_found",
        )

    latest = store.get_latest_state(device_id)

    return {
        "success": True,
        "device": {
            **config,
            "temperature": (
                latest["temperature"]
                if latest else None
            ),
            "status": (
                latest["running_status"]
                if latest else "unknown"
            ),
            "current_alarm": (
                latest["current_alarm"]
                if latest else None
            ),
            "sampled_at": (
                latest["sampled_at"]
                if latest else None
            ),
            "source": (
                latest["source"]
                if latest else None
            ),
        },
        "has_live_data": latest is not None,
    }


# ============================================================
# 3. 查询设备历史温度
# ============================================================

@router.get("/devices/{device_id}/temperatures")
def read_temperatures(
    device_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=1000),
    store: DeviceStateStore = Depends(get_device_store),
):
    device_id = device_id.strip().upper()

    try:
        load_device_config(device_id)

    except (ValueError, KeyError):
        raise HTTPException(
            status_code=404,
            detail="device_not_found",
        )

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)

    records = store.get_temperature_history(
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )

    return {
        "success": True,
        "device_id": device_id,
        "hours": hours,
        "record_count": len(records),
        "limit": limit,
        "records": list(reversed(records)),
    }


# ============================================================
# 4. 查询 Incident
# ============================================================

@router.get("/incidents/{incident_id}")
def read_incident(
    incident_id: str,
    store: IncidentStore = Depends(get_incident_store),
):
    incident = store.get_incident(incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="incident_not_found",
        )

    return {
        "success": True,
        "incident": incident,
    }


# ============================================================
# 5. 查询 Agent Task
# ============================================================

@router.get("/tasks/{task_id}")
def read_task(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
):
    task = store.get_task(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="task_not_found",
        )

    return {
        "success": True,
        "task": task,
    }


# ============================================================
# 6. 查询 Incident 关联的全部任务
# ============================================================

@router.get("/incidents/{incident_id}/tasks")
def read_incident_tasks(
    incident_id: str,
    incident_store: IncidentStore = Depends(
        get_incident_store
    ),
    task_store: TaskStore = Depends(get_task_store),
):
    incident = incident_store.get_incident(incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="incident_not_found",
        )

    tasks = task_store.get_tasks_by_incident(
        incident_id
    )

    return {
        "success": True,
        "incident_id": incident_id,
        "count": len(tasks),
        "tasks": tasks,
    }
