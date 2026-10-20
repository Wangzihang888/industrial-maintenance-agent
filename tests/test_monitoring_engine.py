
import tempfile

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore
from app.monitoring.monitoring_engine import (
    MonitoringEngine,
    classify_temperature,
)
from app.incidents.incident_store import IncidentStore


# ============================================================
# 1. 验证温度边界规则
# ============================================================

assert classify_temperature(52, 65, 75) == "normal"
assert classify_temperature(65, 65, 75) == "warning"
assert classify_temperature(75, 65, 75) == "warning"
assert classify_temperature(75.1, 65, 75) == "critical"

print("测试1通过：Normal / Warning / Critical 边界正确")


# ============================================================
# 2. 创建隔离的测试数据库
# ============================================================

with tempfile.TemporaryDirectory() as temp_dir:

    folder = Path(temp_dir)

    state_store = DeviceStateStore(
        folder / "device_state.db"
    )

    incident_store = IncidentStore(
        folder / "incidents.db"
    )

    engine = MonitoringEngine(
        state_store=state_store,
        incident_store=incident_store,
    )

    base = datetime(
        2026, 10, 10, 10, 0,
        tzinfo=timezone(timedelta(hours=8)),
    )

    def snapshot(
        seconds: int,
        temperature: float,
    ) -> DeviceSnapshot:

        return DeviceSnapshot(
            device_id="RB-001",
            temperature=temperature,
            current_alarm=(
                "E-103" if temperature > 75 else None
            ),
            sampled_at=base + timedelta(seconds=seconds),
        )

    def process(
        item: DeviceSnapshot,
    ) -> dict:

        return engine.process_snapshot(
            snapshot=item,
            warning=65,
            limit=75,
        )

    # ========================================================
    # 测试 2：正常状态
    # ========================================================

    result = process(snapshot(0, 52))

    assert result["risk_level"] == "normal"
    assert result["should_trigger"] is False

    print("测试2通过：正常温度不触发异常")


    # ========================================================
    # 测试 3：首次 Warning
    # ========================================================

    warning_sample = snapshot(2, 68)

    result = process(warning_sample)

    assert result["risk_level"] == "warning"
    assert result["should_trigger"] is True
    assert result["created_incident"] is True

    incident_id = result["incident_id"]

    print("测试3通过：首次 Warning 创建 Incident")


    # ========================================================
    # 测试 4：重复采样
    # ========================================================

    result = process(warning_sample)

    assert result["ignored"] is True
    assert result["should_trigger"] is False

    print("测试4通过：重复采样不触发")


    # ========================================================
    # 测试 5：持续 Warning
    # ========================================================

    result = process(snapshot(4, 70))

    assert result["incident_id"] == incident_id
    assert result["should_trigger"] is False

    print("测试5通过：持续 Warning 不重复触发")


    # ========================================================
    # 测试 6：Warning 升级 Critical
    # ========================================================

    result = process(snapshot(6, 81.5))

    assert result["risk_level"] == "critical"
    assert result["incident_id"] == incident_id
    assert result["risk_escalated"] is True
    assert result["should_trigger"] is True

    print("测试6通过：升级 Critical 触发处置")


    # ========================================================
    # 测试 7：持续 Critical
    # ========================================================

    result = process(snapshot(8, 82))

    assert result["incident_id"] == incident_id
    assert result["should_trigger"] is False

    print("测试7通过：持续 Critical 不重复触发")


    # ========================================================
    # 测试 8：乱序旧采样不能重新触发
    # ========================================================

    result = process(snapshot(3, 69))

    assert result["ignored"] is True
    assert result["should_trigger"] is False

    latest = state_store.get_latest_state("RB-001")

    assert latest["temperature"] == 82

    print("测试8通过：乱序旧采样不影响当前状态")


    # ========================================================
    # 测试 9：数据库中的最高风险
    # ========================================================

    incident = incident_store.get_incident(incident_id)

    assert incident is not None
    assert incident["highest_risk_level"] == "critical"

    print("测试9通过：Incident 保存最高风险")


    # ========================================================
    # 测试 10：温度恢复不自动关闭 Incident
    # ========================================================

    result = process(snapshot(10, 52))

    assert result["risk_level"] == "normal"
    assert result["should_trigger"] is False

    active = incident_store.get_active_incident("RB-001")

    assert active is not None
    assert active["incident_id"] == incident_id

    print("测试10通过：正常采样不会擅自关闭故障")


print("\n全部 Monitoring Engine 测试通过")
