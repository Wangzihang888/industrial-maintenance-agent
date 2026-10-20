
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore


def main():
    now = datetime.now(timezone.utc)

    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "test_device_state.db"
        store = DeviceStateStore(db_path=db_path)

        # 1. RB-001：编码器连续通信失败
        encoder_snapshot = DeviceSnapshot(
            device_id="rb-001",
            temperature=53.0,
            encoder_comm_ok=False,
            encoder_error_count=3,
            current_alarm="e-101",
            sampled_at=now,
        )

        first = store.save_snapshot(encoder_snapshot)
        latest = store.get_latest_state("RB-001")

        assert first["latest_updated"] is True
        assert latest["device_id"] == "RB-001"
        assert latest["encoder_comm_ok"] == 0
        assert latest["encoder_error_count"] == 3
        assert latest["current_alarm"] == "E-101"

        print("通过：RB-001 编码器故障信号已保存")

        # 2. RB-002：伺服驱动器过流
        servo_snapshot = DeviceSnapshot(
            device_id="RB-002",
            temperature=55.0,
            servo_drive_status="fault",
            drive_alarm_subcode="overcurrent",
            current_alarm="E-102",
            sampled_at=now,
        )

        store.save_snapshot(servo_snapshot)
        latest = store.get_latest_state("RB-002")

        assert latest["servo_drive_status"] == "fault"
        assert latest["drive_alarm_subcode"] == "OVERCURRENT"
        assert latest["current_alarm"] == "E-102"

        print("通过：RB-002 伺服故障信号已保存")

        # 3. RB-003：兼容原来的温度采样
        temperature_snapshot = DeviceSnapshot(
            device_id="RB-003",
            temperature=82.0,
            current_alarm="E-103",
            sampled_at=now,
        )

        store.save_snapshot(temperature_snapshot)
        latest = store.get_latest_state("RB-003")

        assert latest["temperature"] == 82.0
        assert latest["encoder_comm_ok"] == 1
        assert latest["servo_drive_status"] == "normal"

        print("通过：RB-003 原有温度采样兼容")

        # 4. 同一采样重复提交
        duplicate = store.save_snapshot(encoder_snapshot)

        assert duplicate["duplicate"] is True
        assert duplicate["latest_updated"] is False

        print("通过：重复采样未再次更新最新状态")

        # 5. 旧采样不能覆盖最新状态
        old_snapshot = encoder_snapshot.model_copy(
            update={
                "sampled_at": now - timedelta(minutes=1),
                "temperature": 40.0,
            }
        )

        old_result = store.save_snapshot(old_snapshot)
        latest = store.get_latest_state("RB-001")

        assert old_result["latest_updated"] is False
        assert latest["temperature"] == 53.0

        print("通过：旧采样不会覆盖最新状态")

        # 6. 同一时间、不同内容必须报错
        conflicting = encoder_snapshot.model_copy(
            update={"encoder_error_count": 2}
        )

        try:
            store.save_snapshot(conflicting)
        except ValueError:
            print("通过：冲突采样被拒绝")
        else:
            raise AssertionError("冲突采样应当被拒绝")

        print("\n全部测试通过！")


if __name__ == "__main__":
    main()
