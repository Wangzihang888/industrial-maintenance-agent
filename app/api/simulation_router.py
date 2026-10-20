
"""
设备模拟监控 API。

保留：
- 原来的单轮模拟任务 API

新增：
- 设备持续运行
- 独立故障场景切换
- 停止模拟
- 查看持续模拟及 Agent 执行状态
"""

from threading import Lock
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
)

from pydantic import BaseModel, Field

from app.monitoring.device_config import load_device_config
from app.monitoring.live_simulation import live_simulation_manager

from app.tasks.task_store import TaskStore
from app.tasks.task_scheduler import process_pending_tasks


router = APIRouter(
    prefix="/api/simulations",
    tags=["Simulation"],
)


# ============================================================
# 1. API 请求模型
# ============================================================

class SimulationRequest(BaseModel):
    device_id: str
    scenario: str = "critical"
    interval: float = 2.0


class LiveStartRequest(BaseModel):
    scenario: str = "normal"
    interval: float = Field(default=2.0, ge=0.5, le=10.0)


class LiveScenarioRequest(BaseModel):
    scenario: str


# ============================================================
# 2. 原有单轮任务状态
# ============================================================

simulation_jobs: dict[str, dict] = {}
jobs_lock = Lock()


def execute_simulation(job_id: str) -> None:
    """保留旧版单轮模拟与 Agent 执行流程。"""

    with jobs_lock:
        job = simulation_jobs[job_id]
        job["status"] = "running"
        device_id = job["device_id"]
        scenario = job["scenario"]
        interval = job["interval"]

    try:
        from scripts.device_simulator import run_simulator
        from app.tasks.agent_runner import run_agent_task

        store = TaskStore()

        results = run_simulator(
            device_id=device_id,
            scenario=scenario,
            interval=interval,
            task_store=store,
        )

        # 从完整 task_results 收集所有新任务，
        # 而不是只读取每次采样的第一个 task_id。
        created_tasks = []

        for result in results:
            for item in result.get("task_results", []):
                task = item.get("task")

                if task and task.get("created") is True:
                    created_tasks.append(task["task_id"])

        with jobs_lock:
            job = simulation_jobs[job_id]
            job["sample_count"] = len(results)
            job["created_task_ids"] = created_tasks
            job["status"] = "executing_agent"

        agent_results = process_pending_tasks(
            task_store=store,
            runner=run_agent_task,
            device_id=device_id,
            limit=20,
        )

        errors = [
            result
            for result in agent_results
            if result.get("status") == "error"
        ]

        with jobs_lock:
            job = simulation_jobs[job_id]
            job["agent_results"] = agent_results

            if errors:
                job["status"] = "completed_with_errors"
                job["error"] = "部分 Agent 任务执行失败"

            elif not created_tasks:
                job["status"] = "no_new_tasks"

            else:
                job["status"] = "completed"

    except Exception as exc:
        with jobs_lock:
            job = simulation_jobs[job_id]
            job["status"] = "failed"
            job["error"] = str(exc)


# ============================================================
# 3. 保留旧版：启动单轮模拟
# ============================================================

@router.post("", status_code=202)
def start_simulation(
    request: SimulationRequest,
    background_tasks: BackgroundTasks,
):
    device_id = request.device_id.strip().upper()

    # 旧接口继续只处理原来的 Critical 演示。
    if request.scenario != "critical":
        raise HTTPException(
            status_code=422,
            detail="unsupported_scenario",
        )

    if not 0.5 <= request.interval <= 10:
        raise HTTPException(
            status_code=422,
            detail="invalid_interval",
        )

    try:
        load_device_config(device_id)
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=404,
            detail="device_not_found",
        )

    # 避免旧版单轮模拟与持续模拟同时写同一设备
    live = live_simulation_manager.get_device(device_id)

    if live and live["status"] in ("running", "stopping"):
        raise HTTPException(
            status_code=409,
            detail="device_live_simulation_running",
        )

    with jobs_lock:
        for existing in simulation_jobs.values():
            if (
                existing["device_id"] == device_id
                and existing["status"] in (
                    "queued",
                    "running",
                    "executing_agent",
                )
            ):
                raise HTTPException(
                    status_code=409,
                    detail="device_simulation_already_running",
                )

        job_id = "SIM-" + uuid4().hex[:12].upper()

        job = {
            "job_id": job_id,
            "device_id": device_id,
            "scenario": request.scenario,
            "interval": request.interval,
            "status": "queued",
            "sample_count": 0,
            "created_task_ids": [],
            "agent_results": [],
            "error": None,
        }

        simulation_jobs[job_id] = job

    background_tasks.add_task(
        execute_simulation,
        job_id,
    )

    return {
        "success": True,
        "job": job.copy(),
    }


# ============================================================
# 4. 新版：查看持续模拟
# ============================================================

@router.get("/live/devices")
def list_live_devices():
    return {
        "success": True,
        "devices": live_simulation_manager.list_devices(),
        "agent_results": (
            live_simulation_manager.list_agent_results()
        ),
    }


# ============================================================
# 5. 新版：启动设备
# ============================================================

@router.post("/live/{device_id}/start")
def start_live_device(
    device_id: str,
    request: LiveStartRequest,
):
    device_id = device_id.strip().upper()

    try:
        load_device_config(device_id)
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=404,
            detail="device_not_found",
        )

    with jobs_lock:
        for job in simulation_jobs.values():
            if (
                job["device_id"] == device_id
                and job["status"] in (
                    "queued",
                    "running",
                    "executing_agent",
                )
            ):
                raise HTTPException(
                    status_code=409,
                    detail="single_run_simulation_running",
                )

    try:
        device = live_simulation_manager.start(
            device_id=device_id,
            scenario=request.scenario,
            interval=request.interval,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409
            if "已经在运行" in str(exc)
            else 422,
            detail=str(exc),
        )

    return {
        "success": True,
        "device": device,
    }


# ============================================================
# 6. 新版：切换场景
# ============================================================

@router.post("/live/{device_id}/scenario")
def change_live_scenario(
    device_id: str,
    request: LiveScenarioRequest,
):
    try:
        device = live_simulation_manager.set_scenario(
            device_id=device_id,
            scenario=request.scenario,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )

    return {
        "success": True,
        "device": device,
    }


# ============================================================
# 7. 新版：停止设备
# ============================================================

@router.post("/live/{device_id}/stop")
def stop_live_device(device_id: str):
    try:
        device = live_simulation_manager.stop(
            device_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    return {
        "success": True,
        "device": device,
    }


# ============================================================
# 8. 保留旧版：查询单轮任务
# ============================================================

@router.get("/{job_id}")
def get_simulation(job_id: str):
    with jobs_lock:
        job = simulation_jobs.get(job_id)

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="simulation_not_found",
            )

        return {
            "success": True,
            "job": job.copy(),
        }
