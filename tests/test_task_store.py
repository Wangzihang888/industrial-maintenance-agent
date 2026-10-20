
import tempfile
from pathlib import Path

from app.tasks.task_store import TaskStore


with tempfile.TemporaryDirectory() as temp_dir:

    store = TaskStore(
        Path(temp_dir) / "tasks.db"
    )

    # 首次创建 Warning 任务
    warning = store.enqueue_task(
        incident_id="INC-001",
        device_id="RB-001",
        risk_level="warning",
    )

    assert warning["created"] is True
    assert warning["status"] == "pending"
    print("测试1通过：创建 Warning 任务")

    # 相同任务不重复创建
    duplicate = store.enqueue_task(
        incident_id="INC-001",
        device_id="RB-001",
        risk_level="warning",
    )

    assert duplicate["created"] is False
    assert duplicate["task_id"] == warning["task_id"]
    print("测试2通过：同一 Incident 同等级任务去重")

    # 领取任务
    assert store.claim_task(warning["task_id"]) is True
    assert store.claim_task(warning["task_id"]) is False
    print("测试3通过：任务只能领取一次")

    # Warning 任务完成
    assert store.transition_task(
        warning["task_id"],
        expected_status="running",
        new_status="completed",
    ) is True
    print("测试4通过：Warning 任务完成")

    # Critical 创建独立任务
    critical = store.enqueue_task(
        incident_id="INC-001",
        device_id="RB-001",
        risk_level="critical",
    )

    assert critical["created"] is True
    assert critical["task_id"] != warning["task_id"]
    print("测试5通过：Critical 使用独立任务")

    # Critical 进入人工审批
    assert store.claim_task(critical["task_id"]) is True

    assert store.transition_task(
        critical["task_id"],
        expected_status="running",
        new_status="waiting_approval",
    ) is True

    assert store.claim_task(critical["task_id"]) is False
    print("测试6通过：等待审批不能重复领取")

    # 审批结束，任务完成
    assert store.transition_task(
        critical["task_id"],
        expected_status="waiting_approval",
        new_status="completed",
    ) is True
    print("测试7通过：审批后任务结束")

    # 一次 Incident 对应两个不同任务
    tasks = store.get_tasks_by_incident("INC-001")

    assert len(tasks) == 2
    assert all(t["status"] == "completed" for t in tasks)
    print("测试8通过：Incident 可关联多个任务")

    # 模拟失败及重新排队
    failed = store.enqueue_task(
        incident_id="INC-002",
        device_id="RB-003",
        risk_level="warning",
    )

    assert store.claim_task(failed["task_id"]) is True

    assert store.transition_task(
        failed["task_id"],
        "running",
        "failed",
        error="模拟执行异常",
    ) is True

    assert store.transition_task(
        failed["task_id"],
        "failed",
        "pending",
    ) is True

    assert store.claim_task(failed["task_id"]) is True

    restored = store.get_task(failed["task_id"])
    assert restored["attempt_count"] == 2
    print("测试9通过：失败任务可重新排队")


print("\n全部 TaskStore 测试通过")
