
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore
from app.monitoring.monitoring_engine import MonitoringEngine
from app.incidents.incident_store import IncidentStore
from app.tasks.monitoring_task_adapter import (
    enqueue_monitoring_events,
)


class FakeTaskStore:
    """
    只用来验证任务登记调用。

    不连接正式 TaskStore 数据库。
    """

    def __init__(self):
        self.tasks = {}

    def enqueue_task(self, incident_id, device_id, risk_level):
        key = (incident_id, risk_level)
        created = key not in self.tasks

        if created:
            self.tasks[key] = {
                "task_id": f"TASK-{len(self.tasks) + 1}",
                "incident_id": incident_id,
                "device_id": device_id,
                "risk_level": risk_level,
            }

        return {
            **self.tasks[key],
            "created": created,
        }


def main():
    now = datetime.now(timezone.utc)

    with TemporaryDirectory() as directory:
        directory = Path(directory)

        state_store = DeviceStateStore(
            db_path=directory / "device_state.db"
        )

        incident_store = IncidentStore(
            db_path=directory / "incidents.db"
        )

        task_store = FakeTaskStore()

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

            return engine.process_snapshot(
                snapshot=snapshot,
                warning=65.0,
                limit=75.0,
            )

        # 1. 正常状态没有故障事件
        normal = process("RB-001", 0)
        assert normal["events"] == []
        print("通过：正常状态不创建故障")

        # 2. E-101 连续错误未达阈值
        early = process(
            "RB-001", 1,
            encoder_comm_ok=False,
            encoder_error_count=2,
        )
        assert early["events"] == []
        print("通过：E-101 未达阈值不触发")

        # 3. E-101 达到阈值
        e101 = process(
            "RB-001", 2,
            encoder_comm_ok=False,
            encoder_error_count=3,
        )

        assert len(e101["events"]) == 1
        assert e101["events"][0]["alarm_code"] == "E-101"
        assert e101["events"][0]["should_trigger"] is True

        e101_id = e101["events"][0]["incident_id"]

        print("通过：E-101 创建 Incident")

        # 4. 同一 E-101 继续存在，不重复触发
        repeated = process(
            "RB-001", 3,
            encoder_comm_ok=False,
            encoder_error_count=4,
        )

        assert repeated["events"][0]["incident_id"] == e101_id
        assert repeated["events"][0]["should_trigger"] is False

        print("通过：持续 E-101 不重复触发")

        # 5. RB-002 发生 E-102
        e102 = process(
            "RB-002", 0,
            servo_drive_status="fault",
            drive_alarm_subcode="overcurrent",
        )

        assert len(e102["events"]) == 1
        assert e102["events"][0]["alarm_code"] == "E-102"
        assert e102["events"][0]["incident_key"] == "servo:drive_fault"

        print("通过：E-102 创建独立 Incident")

        # 6. RB-003 出现过温，且设备报告 E-103
        e103 = process(
            "RB-003", 0,
            temperature=82.0,
            current_alarm="E-103",
        )

        assert len(e103["events"]) == 1
        assert e103["events"][0]["alarm_code"] == "E-103"
        assert e103["events"][0]["risk_level"] == "critical"

        print("通过：E-103 过温异常正常识别")

        # 7. 同一次采样同时发生两种故障
        multiple = process(
            "RB-001", 4,
            temperature=82.0,
            current_alarm="E-103",
            encoder_comm_ok=False,
            encoder_error_count=5,
        )

        keys = {
            event["incident_key"]
            for event in multiple["events"]
        }

        assert keys == {
            "encoder:communication",
            "temperature:overheat",
        }

        # E-101 是持续故障，不应该重复创建任务
        assert multiple["events"][0]["should_trigger"] is False

        print("通过：同一次采样识别多个故障")

        # 8. 将三台设备的首次异常登记为模拟任务
        all_task_results = []

        for monitoring_result in (e101, e102, e103, multiple):
            all_task_results.extend(
                enqueue_monitoring_events(
                    monitoring_result=monitoring_result,
                    task_store=task_store,
                )
            )

        created_tasks = [
            item for item in all_task_results
            if item["enqueued"] and item["task"]["created"]
        ]

        # E-101、E-102、E-103、RB-001过温，共4个
        assert len(created_tasks) == 4
        assert len(task_store.tasks) == 4

        print("通过：四个独立处置需求创建四个任务")

        # 9. 同一条采样再次投递不触发事件
        duplicate = process(
            "RB-001", 4,
            temperature=82.0,
            current_alarm="E-103",
            encoder_comm_ok=False,
            encoder_error_count=5,
        )

        assert duplicate["ignored"] is True
        assert duplicate["events"] == []

        print("通过：重复采样不会再次触发任务")

        print("\n多故障监控与任务适配测试全部通过！")


if __name__ == "__main__":
    main()
