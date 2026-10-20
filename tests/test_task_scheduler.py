
import tempfile
from pathlib import Path

from app.tasks.task_store import TaskStore
from app.tasks.task_scheduler import process_pending_tasks


with tempfile.TemporaryDirectory() as temp_dir:

    store = TaskStore(
        Path(temp_dir) / "tasks.db"
    )

    # 1. 创建两个待执行任务
    warning = store.enqueue_task(
        incident_id="INC-001",
        device_id="RB-001",
        risk_level="warning",
    )

    critical = store.enqueue_task(
        incident_id="INC-001",
        device_id="RB-001",
        risk_level="critical",
    )

    pending = store.list_pending_tasks()

    assert len(pending) == 2

    print("测试1通过：Scheduler 能发现两个 pending 任务")

    # 2. 构造测试 Runner
    # 不调用大模型或真实 LangGraph
    executed = []

    def fake_runner(
        task_id: str,
        task_store: TaskStore,
    ) -> dict:

        assert task_store.claim_task(task_id) is True

        assert task_store.transition_task(
            task_id,
            expected_status="running",
            new_status="completed",
        ) is True

        executed.append(task_id)

        return {
            "task_id": task_id,
            "started": True,
            "status": "completed",
        }

    # 3. 让 Scheduler 执行任务
    results = process_pending_tasks(
        task_store=store,
        runner=fake_runner,
    )

    assert len(results) == 2
    assert set(executed) == {
        warning["task_id"],
        critical["task_id"],
    }

    print("测试2通过：Scheduler 自动调用 Runner")

    # 4. 确认任务已经完成
    assert store.list_pending_tasks() == []

    print("测试3通过：已完成任务不再被扫描")

    # 5. 再扫描一次，不应重复执行
    results = process_pending_tasks(
        task_store=store,
        runner=fake_runner,
    )

    assert results == []
    assert len(executed) == 2

    print("测试4通过：重复扫描不重复执行")

    # 6. 测试设备筛选
    other = store.enqueue_task(
        incident_id="INC-002",
        device_id="RB-003",
        risk_level="warning",
    )

    assert store.list_pending_tasks(
        device_id="RB-001"
    ) == []

    filtered = store.list_pending_tasks(
        device_id="RB-003"
    )

    assert len(filtered) == 1
    assert filtered[0]["task_id"] == other["task_id"]

    print("测试5通过：按设备编号筛选任务")

    # 7. waiting_approval 不能被重新领取
    assert store.claim_task(other["task_id"]) is True

    assert store.transition_task(
        other["task_id"],
        expected_status="running",
        new_status="waiting_approval",
    ) is True

    assert store.list_pending_tasks() == []

    print("测试6通过：等待审批任务不会重新调度")


print("\n全部 Task Scheduler 测试通过")
