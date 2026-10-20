
from fastapi import APIRouter, HTTPException

from app.api.schemas import ApprovalRequest
from app.tasks.approval_service import resume_agent_approval
from app.tasks.task_store import TaskStore


router = APIRouter(
    prefix="/api",
    tags=["Approval"],
)


@router.post("/tasks/{task_id}/approval")
def approve_task(
    task_id: str,
    request: ApprovalRequest,
):
    """
    运维人员审批自动 Agent 维修申请。

    支持：
        critical：严重过温
        fault：E-101 / E-102 设备故障

    warning 不需要人工审批。

    本接口不直接创建维修工单。
    """

    store = TaskStore()
    task = store.get_task(task_id)

    # 1. 检查任务是否存在
    if task is None:
        raise HTTPException(
            status_code=404,
            detail="task_not_found",
        )

    # 2. 判断是否属于需要审批的任务
    if task["risk_level"] not in (
        "critical",
        "fault",
    ):
        raise HTTPException(
            status_code=409,
            detail="task_does_not_require_approval",
        )

    # 3. 已经完成的任务不能重复审批
    if task["status"] == "completed":
        return {
            "task_id": task_id,
            "status": "completed",
            "resumed": False,
            "reason": "task_already_completed",
        }

    # 4. 只有等待审批的任务才能提交决定
    if task["status"] != "waiting_approval":
        raise HTTPException(
            status_code=409,
            detail="task_not_waiting_approval",
        )

    # 5. 交给审批服务恢复对应 LangGraph
    try:
        result = resume_agent_approval(
            task_id=task_id,
            approved=request.approved,
            task_store=store,
        )

    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return result
