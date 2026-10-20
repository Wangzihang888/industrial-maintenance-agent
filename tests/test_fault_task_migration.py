
import sqlite3

from pathlib import Path
from tempfile import TemporaryDirectory

from app.tasks.task_store import TaskStore
from app.incidents.incident_store import IncidentStore


def main():
    with TemporaryDirectory() as directory:
        folder = Path(directory)
        task_db = folder / "tasks.db"
        incident_db = folder / "incidents.db"

        # 1. 模拟旧版 TaskStore 的数据库结构
        conn = sqlite3.connect(task_db)

        with conn:
            conn.execute("""
                CREATE TABLE agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    risk_level TEXT NOT NULL
                        CHECK (
                            risk_level IN ('warning', 'critical')
                        ),
                    thread_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (
                            status IN (
                                'pending',
                                'running',
                                'waiting_approval',
                                'completed',
                                'failed'
                            )
                        ),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (incident_id, risk_level)
                )
            """)

            conn.execute("""
                INSERT INTO agent_tasks (
                    task_id,
                    incident_id,
                    device_id,
                    risk_level,
                    thread_id,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "TASK-OLD",
                "INC-OLD",
                "RB-001",
                "critical",
                "auto:TASK-OLD",
                "waiting_approval",
                "2026-10-14T10:00:00+00:00",
                "2026-10-14T10:00:00+00:00",
            ))

        conn.close()

        # 2. 初始化新版 TaskStore，自动迁移旧表
        store = TaskStore(db_path=task_db)

        old_task = store.get_task("TASK-OLD")

        assert old_task is not None
        assert old_task["status"] == "waiting_approval"
        assert old_task["risk_level"] == "critical"
        assert old_task["thread_id"] == "auto:TASK-OLD"

        print("通过：旧任务和审批等待状态完整保留")

        # 3. 新版本允许 fault
        fault_task = store.enqueue_task(
            incident_id="INC-NEW-101",
            device_id="RB-001",
            risk_level="fault",
        )

        assert fault_task["created"] is True
        assert fault_task["risk_level"] == "fault"
        assert fault_task["status"] == "pending"

        print("通过：可以创建 fault 类型任务")

        # 4. 相同 Incident 不重复创建
        repeated = store.enqueue_task(
            incident_id="INC-NEW-101",
            device_id="RB-001",
            risk_level="fault",
        )

        assert repeated["created"] is False
        assert repeated["task_id"] == fault_task["task_id"]

        print("通过：重复 fault 任务正确去重")

        # 5. 再次初始化，不应该重复迁移
        another_store = TaskStore(db_path=task_db)

        assert another_store.get_task("TASK-OLD") is not None
        assert another_store.get_task(
            fault_task["task_id"]
        ) is not None

        print("通过：数据库迁移具有幂等性")

        # 6. IncidentStore 支持 E-101 fault
        incidents = IncidentStore(db_path=incident_db)

        e101 = incidents.record_anomaly(
            device_id="RB-001",
            incident_key="encoder:communication",
            alarm_code="E-101",
            risk_level="fault",
        )

        assert e101["created_incident"] is True
        assert e101["highest_risk_level"] == "fault"

        repeated_e101 = incidents.record_anomaly(
            device_id="RB-001",
            incident_key="encoder:communication",
            alarm_code="E-101",
            risk_level="fault",
        )

        assert repeated_e101["created_incident"] is False
        assert repeated_e101["should_trigger"] is False

        print("通过：E-101 fault Incident 正确创建和去重")

        # 7. 温度 Warning → Critical 仍然正常
        warning = incidents.record_anomaly(
            device_id="RB-003",
            risk_level="warning",
        )

        critical = incidents.record_anomaly(
            device_id="RB-003",
            risk_level="critical",
            alarm_code="E-103",
        )

        assert (
            warning["incident_id"]
            == critical["incident_id"]
        )
        assert critical["risk_escalated"] is True

        print("通过：温度 Warning → Critical 不受影响")

        print("\n数据库兼容与 fault 业务状态测试全部通过！")


if __name__ == "__main__":
    main()
