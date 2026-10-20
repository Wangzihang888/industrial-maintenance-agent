
"""
自动 Agent 任务的人工审批恢复服务。

职责：
1. 根据 task_id 查找任务
2. 检查任务是否等待审批
3. 验证 LangGraph Checkpoint
4. 通过 Command(resume) 恢复工作流
5. 验证审批与正式工单结果
6. 更新 TaskStore 状态

并发保护：
同一个 Python 进程内，同一 task_id 的审批请求
必须串行执行。

注意：
这是进程内线程互斥，不是跨进程分布式锁。
"""

from contextlib import contextmanager
from threading import Lock

from langgraph.types import Command

from app.agent.graph import graph
from app.tasks.task_store import TaskStore


# ============================================================
# 1. 审批锁注册表
# ============================================================

# 保护锁注册表本身
_APPROVAL_LOCKS_GUARD = Lock()

# 每个 task_id 对应独立的互斥锁
_APPROVAL_LOCKS = {}


# ============================================================
# 2. 同一任务审批互斥
# ============================================================

@contextmanager
def exclusive_task_approval(task_id: str):
    """
    确保同一 Python 进程中：

    相同 task_id 的审批串行执行；
    不同 task_id 使用不同锁。

    users 记录正在使用或等待锁的线程数量。

    所有使用者退出后删除锁记录，
    避免长期保存已经完成的任务锁。
    """

    # --------------------------------------------------------
    # 2.1 获取或创建任务专属锁
    # --------------------------------------------------------

    with _APPROVAL_LOCKS_GUARD:

        entry = _APPROVAL_LOCKS.get(task_id)

        if entry is None:

            entry = {
                "lock": Lock(),
                "users": 0,
            }

            _APPROVAL_LOCKS[task_id] = entry

        entry["users"] += 1

    # --------------------------------------------------------
    # 2.2 独占执行审批逻辑
    # --------------------------------------------------------

    try:

        with entry["lock"]:
            yield

    # --------------------------------------------------------
    # 2.3 释放并清理锁记录
    # --------------------------------------------------------

    finally:

        with _APPROVAL_LOCKS_GUARD:

            entry["users"] -= 1

            if entry["users"] == 0:
                _APPROVAL_LOCKS.pop(task_id, None)


# ============================================================
# 3. 审批服务公开入口
# ============================================================

def resume_agent_approval(
    task_id: str,
    approved: bool,
    task_store: TaskStore | None = None,
) -> dict:
    """
    恢复等待人工审批的自动任务。

    对同一个 task_id 加锁后，
    必须重新读取 TaskStore 状态。

    避免两个请求同时读取 waiting_approval，
    然后重复执行 Graph。
    """

    if not isinstance(approved, bool):
        raise ValueError("approved 必须是布尔值")

    with exclusive_task_approval(task_id):

        return _resume_approval_locked(
            task_id=task_id,
            approved=approved,
            task_store=task_store,
        )


# ============================================================
# 4. 锁保护下的实际审批
# ============================================================

def _resume_approval_locked(
    task_id: str,
    approved: bool,
    task_store: TaskStore | None,
) -> dict:

    if task_store is None:
        task_store = TaskStore()

    # --------------------------------------------------------
    # 4.1 重新读取最新 Task 状态
    # --------------------------------------------------------

    task = task_store.get_task(task_id)

    if task is None:
        raise ValueError(
            f"任务不存在：{task_id}"
        )

    # 第一个审批请求完成后，
    # 第二个请求获得锁时会进入这里。
    if task["status"] == "completed":

        return {
            "task_id": task_id,
            "resumed": False,
            "status": "completed",
            "reason": "task_already_completed",
        }

    if task["status"] != "waiting_approval":

        raise ValueError(
            f"任务当前状态为 {task['status']}，"
            "不允许审批"
        )

    # --------------------------------------------------------
    # 4.2 读取 LangGraph Checkpoint
    # --------------------------------------------------------

    config = {
        "configurable": {
            "thread_id": task["thread_id"],
        },
        "recursion_limit": 30,
    }

    snapshot = graph.get_state(config)

    # --------------------------------------------------------
    # 4.3 检查是否停在审批节点
    # --------------------------------------------------------

    interrupted = any(
        item.name == "approval"
        and bool(getattr(item, "interrupts", ()))
        for item in snapshot.tasks
    )

    if not interrupted:

        raise RuntimeError(
            "没有找到等待审批的 LangGraph Interrupt。"
            "任务状态和检查点可能不一致，"
            "需要人工检查，禁止盲目恢复。"
        )

    state_before = snapshot.values

    if state_before.get("task_id") != task_id:

        raise RuntimeError(
            "LangGraph 检查点的 task_id 不匹配"
        )

    if (
        state_before.get("incident_id")
        != task["incident_id"]
    ):

        raise RuntimeError(
            "LangGraph 检查点的 incident_id 不匹配"
        )

    if (
        state_before.get("ticket_status")
        != "pending_approval"
    ):

        raise RuntimeError(
            "工单申请没有处于 pending_approval 状态"
        )

    # --------------------------------------------------------
    # 4.4 恢复 LangGraph
    # --------------------------------------------------------

    graph.invoke(
        Command(
            resume={"approved": approved}
        ),
        config=config,
    )

    # --------------------------------------------------------
    # 4.5 验证恢复结果
    # --------------------------------------------------------

    after = graph.get_state(config)

    if after.next:

        raise RuntimeError(
            "审批恢复后 Graph 尚未结束，"
            "暂不将任务标记为 completed"
        )

    state = after.values

    if state.get("ticket_approved") is not approved:

        raise RuntimeError(
            "Graph 中的审批结果与输入不一致"
        )

    # --------------------------------------------------------
    # 4.6 审批通过
    # --------------------------------------------------------

    if approved:

        if (
            state.get("ticket_created") is not True
            or state.get("ticket_status") != "created"
            or not state.get("ticket_id")
        ):

            raise RuntimeError(
                "人工已批准，但正式工单创建未成功；"
                "请检查 Graph 与数据库，勿直接重复审批"
            )

    # --------------------------------------------------------
    # 4.7 审批拒绝
    # --------------------------------------------------------

    else:

        if (
            state.get("ticket_approved") is not False
            or state.get("ticket_status") != "rejected"
        ):

            raise RuntimeError(
                "拒绝审批结果异常，"
                "请检查 Graph 状态"
            )

    # --------------------------------------------------------
    # 4.8 更新 TaskStore
    # --------------------------------------------------------

    changed = task_store.transition_task(
        task_id=task_id,
        expected_status="waiting_approval",
        new_status="completed",
    )

    if not changed:

        raise RuntimeError(
            "Graph 已结束，但 TaskStore 更新失败；"
            "需要对账，禁止重新执行审批"
        )

    # --------------------------------------------------------
    # 4.9 返回审批结果
    # --------------------------------------------------------

    return {
        "task_id": task_id,
        "incident_id": task["incident_id"],
        "device_id": task["device_id"],
        "approved": approved,
        "resumed": True,
        "status": "completed",
        "ticket_status": state.get("ticket_status"),
        "ticket_created": state.get(
            "ticket_created",
            False,
        ),
        "ticket_id": state.get("ticket_id"),
    }
