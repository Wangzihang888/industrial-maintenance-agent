
import tempfile
from pathlib import Path

from app.tasks.task_store import TaskStore
from app.tasks.monitoring_task_adapter import (
    enqueue_monitoring_result,
)


with tempfile.TemporaryDirectory() as temp_dir:

    store = TaskStore(
        Path(temp_dir) / "agent_tasks.db"
    )

    # 测试 1：Normal 不产生任务
    normal_result = {
        "device_id": "RB-001",
        "risk_level": "normal",
        "incident_id": None,
        "should_trigger": False,
    }

    result = enqueue_monitoring_result(
        normal_result,
        store,
    )

    assert result["enqueued"] is False
    print("测试1通过：Normal 不创建任务")

    # 测试 2：首次 Warning 创建任务
    warning_result = {
        "device_id": "RB-001",
        "risk_level": "warning",
        "incident_id": "INC-TEST-001",
        "should_trigger": True,
    }

    result = enqueue_monitoring_result(
        warning_result,
        store,
    )

    warning_task = result["task"]

    assert warning_task["created"] is True
    assert warning_task["status"] == "pending"
    assert warning_task["risk_level"] == "warning"

    print("测试2通过：Warning 创建 pending 任务")

    # 测试 3：相同处置需求不重复登记
    result = enqueue_monitoring_result(
        warning_result,
        store,
    )

    assert result["task"]["created"] is False
    assert result["task"]["task_id"] == warning_task["task_id"]

    print("测试3通过：重复 Warning 任务去重")

    # 测试 4：Critical 生成不同任务
    critical_result = {
        "device_id": "RB-001",
        "risk_level": "critical",
        "incident_id": "INC-TEST-001",
        "should_trigger": True,
    }

    result = enqueue_monitoring_result(
        critical_result,
        store,
    )

    critical_task = result["task"]

    assert critical_task["created"] is True
    assert critical_task["task_id"] != warning_task["task_id"]

    print("测试4通过：Critical 创建独立任务")

    # 测试 5：同一个 Incident 关联两个任务
    tasks = store.get_tasks_by_incident(
        "INC-TEST-001"
    )

    assert len(tasks) == 2
    assert {t["risk_level"] for t in tasks} == {
        "warning",
        "critical",
    }

    print("测试5通过：Incident 关联 Warning/Critical")

    # 测试 6：持续异常不重复登记
    ongoing = {
        "device_id": "RB-001",
        "risk_level": "critical",
        "incident_id": "INC-TEST-001",
        "should_trigger": False,
    }

    result = enqueue_monitoring_result(
        ongoing,
        store,
    )

    assert result["enqueued"] is False

    print("测试6通过：持续异常不重复登记")


print("\n全部监控任务适配器测试通过")
