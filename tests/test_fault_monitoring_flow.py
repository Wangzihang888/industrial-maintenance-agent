
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore
from app.monitoring.monitoring_engine import MonitoringEngine
from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore
from app.tasks.monitoring_task_adapter import enqueue_monitoring_events


def main():
    now = datetime.now(timezone.utc)

    with TemporaryDirectory() as folder:
        folder = Path(folder)

        state_store = DeviceStateStore(folder / "states.db")
        incident_store = IncidentStore(folder / "incidents.db")
        task_store = TaskStore(folder / "tasks.db")

        engine = MonitoringEngine(
            state_store=state_store,
            incident_store=incident_store,
        )

        def process(device_id, seconds, temperature=53.0, **signals):
            snapshot = DeviceSnapshot(
                device_id=device_id,
                temperature=temperature,
                sampled_at=now + timedelta(seconds=seconds),
                **signals,
            )

            result = engine.process_snapshot(
                snapshot=snapshot,
                warning=65.0,
                limit=75.0,
            )

            tasks = enqueue_monitoring_events(
                monitoring_result=result,
                task_store=task_store,
            )

            return result, tasks

        # E-101：温度正常，但编码器通信异常
        e101, tasks101 = process(
            "RB-001", 0,
            encoder_comm_ok=False,
            encoder_error_count=3,
        )

        assert e101["risk_level"] == "normal"
        assert e101["events"][0]["risk_level"] == "fault"
        assert e101["events"][0]["alarm_code"] == "E-101"
        assert tasks101[0]["task"]["risk_level"] == "fault"
        assert tasks101[0]["task"]["created"] is True

        print("通过：E-101 以 fault 创建真实任务")

        # E-101 持续异常：不重复创建任务
        again, again_tasks = process(
            "RB-001", 1,
            encoder_comm_ok=False,
            encoder_error_count=4,
        )

        assert again["events"][0]["should_trigger"] is False
        assert again_tasks[0]["task"] is None

        print("通过：持续 E-101 不重复登记")

        # E-102：温度正常，驱动器故障
        e102, tasks102 = process(
            "RB-002", 0,
            servo_drive_status="fault",
            drive_alarm_subcode="OVERCURRENT",
        )

        assert e102["risk_level"] == "normal"
        assert e102["events"][0]["risk_level"] == "fault"
        assert e102["events"][0]["alarm_code"] == "E-102"
        assert tasks102[0]["task"]["risk_level"] == "fault"

        print("通过：E-102 以 fault 创建真实任务")

        # E-103：温度达到 Warning
        warning, warning_tasks = process(
            "RB-003", 0,
            temperature=68.0,
        )

        assert warning["events"][0]["risk_level"] == "warning"
        assert warning_tasks[0]["task"]["risk_level"] == "warning"

        print("通过：温度 Warning 保持原有行为")

        # E-103：温度升级 Critical
        critical, critical_tasks = process(
            "RB-003", 1,
            temperature=82.0,
            current_alarm="E-103",
        )

        assert critical["events"][0]["risk_level"] == "critical"
        assert critical["events"][0]["risk_escalated"] is True
        assert critical_tasks[0]["task"]["risk_level"] == "critical"

        print("通过：温度 Critical 升级并创建任务")

        assert len(task_store.list_tasks()) == 4

        print("\n多故障监控与真实 TaskStore 测试全部通过！")


if __name__ == "__main__":
    main()
