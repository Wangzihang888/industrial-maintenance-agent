
import tempfile
from pathlib import Path

from app.monitoring.device_state_models import (
    DeviceSnapshot,
)
from app.incidents.incident_store import (
    IncidentStore,
)


# ============================================================
# 测试 DeviceSnapshot
# ============================================================

snapshot = DeviceSnapshot.model_validate({
    "device_id": "rb-001",
    "temperature": 81.5,
    "current_alarm": "e-103",
    "running_status": "running",
    "sampled_at": "2026-10-09T10:00:00+08:00",
    "source": "device_simulator",
})

assert snapshot.device_id == "RB-001"
assert snapshot.current_alarm == "E-103"

print("测试1通过：设备状态模型正常")


# ============================================================
# 测试 Incident 生命周期
# ============================================================

with tempfile.TemporaryDirectory() as temp_dir:

    store = IncidentStore(
        Path(temp_dir) / "incidents.db"
    )

    # 第一次 Warning
    result1 = store.record_anomaly(
        device_id="RB-001",
        risk_level="warning",
    )

    assert result1["created_incident"] is True
    assert result1["should_trigger"] is True

    incident_id = result1["incident_id"]

    print("测试2通过：首次 Warning 产生 Incident")

    # 持续 Warning
    result2 = store.record_anomaly(
        device_id="RB-001",
        risk_level="warning",
    )

    assert result2["incident_id"] == incident_id
    assert result2["should_trigger"] is False

    print("测试3通过：持续 Warning 不重复触发")

    # 升级 Critical
    result3 = store.record_anomaly(
        device_id="RB-001",
        risk_level="critical",
        alarm_code="E-103",
    )

    assert result3["incident_id"] == incident_id
    assert result3["risk_escalated"] is True
    assert result3["should_trigger"] is True

    print("测试4通过：Warning 升级 Critical")

    # 持续 Critical
    result4 = store.record_anomaly(
        device_id="RB-001",
        risk_level="critical",
        alarm_code="E-103",
    )

    assert result4["incident_id"] == incident_id
    assert result4["should_trigger"] is False

    print("测试5通过：持续 Critical 不重复触发")

    # 查询当前异常
    active = store.get_active_incident("RB-001")

    assert active["incident_id"] == incident_id
    assert active["highest_risk_level"] == "critical"

    print("测试6通过：正确读取活动 Incident")

    # 关闭异常
    assert store.close_incident(incident_id) is True

    # 再次出现异常，应创建新 Incident
    result5 = store.record_anomaly(
        device_id="RB-001",
        risk_level="warning",
    )

    assert result5["incident_id"] != incident_id
    assert result5["should_trigger"] is True

    print("测试7通过：关闭后允许创建新 Incident")

print("\n全部测试通过")
