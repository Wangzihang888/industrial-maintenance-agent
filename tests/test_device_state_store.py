
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore


def make_snapshot(
    temperature: float,
    timestamp: datetime,
) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id="rb-001",
        temperature=temperature,
        current_alarm="E-103" if temperature > 75 else None,
        running_status="running",
        sampled_at=timestamp,
        source="device_simulator",
    )


with tempfile.TemporaryDirectory() as temp_dir:

    store = DeviceStateStore(
        Path(temp_dir) / "device_state.db"
    )

    base_time = datetime(
        2026, 10, 9, 10, 0,
        tzinfo=timezone(timedelta(hours=8)),
    )

    # 1. 首次采样
    first = make_snapshot(52.0, base_time)
    result1 = store.save_snapshot(first)

    assert result1["duplicate"] is False
    assert result1["latest_updated"] is True
    print("测试1通过：首次保存设备采样")

    # 2. 保存更新的采样
    second = make_snapshot(
        81.5,
        base_time + timedelta(seconds=2),
    )
    result2 = store.save_snapshot(second)

    assert result2["latest_updated"] is True
    print("测试2通过：更新设备最新状态")

    # 3. 查询最新状态
    latest = store.get_latest_state("RB-001")

    assert latest is not None
    assert latest["temperature"] == 81.5
    assert latest["current_alarm"] == "E-103"
    print("测试3通过：读取最新设备状态")

    # 4. 重复采样不重复保存
    duplicate = store.save_snapshot(second)

    assert duplicate["duplicate"] is True
    assert duplicate["latest_updated"] is False
    print("测试4通过：重复采样去重")

    # 5. 旧采样不能覆盖最新状态
    older = make_snapshot(
        68.0,
        base_time + timedelta(seconds=1),
    )
    result5 = store.save_snapshot(older)

    assert result5["latest_updated"] is False

    latest = store.get_latest_state("RB-001")
    assert latest["temperature"] == 81.5
    print("测试5通过：旧采样不覆盖新状态")

    # 6. 查询历史记录
    records = store.get_temperature_history(
        device_id="RB-001",
        start_time=base_time,
        end_time=base_time + timedelta(seconds=5),
    )

    assert len(records) == 3
    assert [item["temperature"] for item in records] == [
        81.5, 68.0, 52.0
    ]
    print("测试6通过：历史温度查询和排序")

    # 7. 相同采样身份、不同内容不允许写入
    conflict = make_snapshot(
        99.0,
        base_time + timedelta(seconds=2),
    )

    try:
        store.save_snapshot(conflict)
        raise AssertionError("冲突采样不应该保存")

    except ValueError as exc:
        assert "对应不同的数据" in str(exc)

    print("测试7通过：拒绝冲突采样")

    # 8. 重新建立存储实例后仍然可查询
    another_store = DeviceStateStore(
        Path(temp_dir) / "device_state.db"
    )

    restored = another_store.get_latest_state("RB-001")

    assert restored["temperature"] == 81.5
    print("测试8通过：SQLite 数据持久化")


print("\n全部 Device State Store 测试通过")
