
"""
运维工作台列表 API。

只读接口：
- 设备列表
- Incident 列表
- Agent 任务列表
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from app.monitoring.device_config import (
    DEFAULT_CONFIG_PATH,
    load_device_config,
)
from app.monitoring.device_state_store import DeviceStateStore
from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore

from app.api.operations_router import (
    get_device_store,
    get_incident_store,
    get_task_store,
)


router = APIRouter(
    prefix="/api",
    tags=["Dashboard"],
)


# ============================================================
# 1. 设备列表
# ============================================================

@router.get("/devices")
def list_devices(
    store: DeviceStateStore = Depends(get_device_store),
):
    with DEFAULT_CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        configs = json.load(file)

    devices = []

    for device_id in configs:

        config = load_device_config(device_id)

        latest = store.get_latest_state(device_id)

        device = {
            **config,
            "temperature": (
                latest["temperature"] if latest else None
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
            "has_live_data": latest is not None,
        }

        devices.append(device)

    return {
        "success": True,
        "count": len(devices),
        "devices": devices,
    }


# ============================================================
# 2. Incident 列表
# ============================================================

@router.get("/incidents")
def list_incidents(
    status: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    store: IncidentStore = Depends(get_incident_store),
):
    if status not in (None, "open", "closed"):
        raise HTTPException(
            status_code=422,
            detail="invalid_incident_status",
        )

    try:
        incidents = store.list_incidents(
            status=status,
            device_id=device_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        "count": len(incidents),
        "incidents": incidents,
    }


# ============================================================
# 3. Agent 任务列表
# ============================================================

@router.get("/tasks")
def list_tasks(
    status: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    store: TaskStore = Depends(get_task_store),
):
    try:
        tasks = store.list_tasks(
            status=status,
            device_id=device_id,
            limit=limit,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        "count": len(tasks),
        "tasks": tasks,
    }
