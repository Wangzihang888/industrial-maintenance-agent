
import tempfile
from pathlib import Path

from app.monitoring.device_state_store import DeviceStateStore
from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore

from scripts.device_simulator import run_simulator


with tempfile.TemporaryDirectory() as temp_dir:

    folder = Path(temp_dir)

    state_store = DeviceStateStore(
        folder / "device_state.db"
    )

    incident_store = IncidentStore(
        folder / "incidents.db"
    )

    task_store = TaskStore(
        folder / "agent_tasks.db"
    )

    # 模拟 RB-001 从 Normal 进入 Critical
    results = run_simulator(
        device_id="RB-001",
        scenario="critical",
        interval=0,
        state_store=state_store,
        incident_store=incident_store,
        task_store=task_store,
    )

    assert len(results) == 7
    print("测试1通过：七次采样完成")

    # Warning、Critical 分别生成一个任务
    created = [
        result
        for result in results
        if result["task_created"]
    ]

    assert len(created) == 2

    assert [item["risk_level"] for item in created] == [
        "warning",
        "critical",
    ]

    print("测试2通过：Warning 和 Critical 各生成任务")

    # 两个任务属于同一个 Incident
    incident_id = created[0]["incident_id"]

    assert created[1]["incident_id"] == incident_id

    tasks = task_store.get_tasks_by_incident(incident_id)

    assert len(tasks) == 2

    assert {task["risk_level"] for task in tasks} == {
        "warning",
        "critical",
    }

    print("测试3通过：两个任务关联同一 Incident")

    # 任务已保存，等待 Runner 执行
    assert all(
        task["status"] == "pending"
        for task in tasks
    )

    print("测试4通过：任务已持久化为 pending")

    # 新实例仍然能查询任务
    another_store = TaskStore(
        folder / "agent_tasks.db"
    )

    restored = another_store.get_tasks_by_incident(
        incident_id
    )

    assert len(restored) == 2

    print("测试5通过：重新连接后可恢复任务记录")


print("\n全部模拟器任务登记测试通过")
