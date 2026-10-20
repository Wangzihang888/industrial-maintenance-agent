
import tempfile
from pathlib import Path

from app.monitoring.device_config import load_device_config
from app.monitoring.device_state_store import DeviceStateStore
from app.incidents.incident_store import IncidentStore
from scripts.device_simulator import run_simulator


# ============================================================
# 测试 1：读取真实设备配置
# ============================================================

rb001 = load_device_config("RB-001")
rgv001 = load_device_config("RGV-001")

assert rb001["temperature_warning"] == 65.0
assert rb001["temperature_limit"] == 75.0

assert rgv001["temperature_warning"] == 60.0
assert rgv001["temperature_limit"] == 70.0

print("测试1通过：读取不同设备的实际温度阈值")


# ============================================================
# 测试 2：模拟器与监控引擎集成
# ============================================================

with tempfile.TemporaryDirectory() as temp_dir:

    folder = Path(temp_dir)

    state_store = DeviceStateStore(
        folder / "device_state.db"
    )

    incident_store = IncidentStore(
        folder / "incidents.db"
    )

    results = run_simulator(
        device_id="RB-001",
        scenario="critical",
        interval=0,
        state_store=state_store,
        incident_store=incident_store,
    )

    assert len(results) == 7

    assert [r["risk_level"] for r in results] == [
        "normal",
        "normal",
        "warning",
        "warning",
        "critical",
        "critical",
        "critical",
    ]

    print("测试2通过：七次采样的风险判断正确")


    # ========================================================
    # 测试 3：Warning 与 Critical 各触发一次
    # ========================================================

    triggered = [
        result
        for result in results
        if result["should_trigger"]
    ]

    assert len(triggered) == 2

    assert triggered[0]["risk_level"] == "warning"
    assert triggered[1]["risk_level"] == "critical"

    assert (
        triggered[0]["incident_id"]
        == triggered[1]["incident_id"]
    )

    print("测试3通过：Warning 和 Critical 处置信号正确")


    # ========================================================
    # 测试 4：最新设备状态
    # ========================================================

    latest = state_store.get_latest_state("RB-001")

    assert latest is not None
    assert latest["temperature"] == 82.0
    assert latest["current_alarm"] == "E-103"

    print("测试4通过：最新设备状态为 82℃")


    # ========================================================
    # 测试 5：Incident 最高风险
    # ========================================================

    incident_id = triggered[0]["incident_id"]

    incident = incident_store.get_incident(
        incident_id
    )

    assert incident is not None
    assert incident["highest_risk_level"] == "critical"
    assert incident["status"] == "open"

    print("测试5通过：Incident 升级为 Critical")


    # ========================================================
    # 测试 6：历史采样真实写入 SQLite
    # ========================================================

    conn = state_store._connect()

    try:
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM temperature_history
            WHERE device_id = ?
            """,
            ("RB-001",),
        ).fetchone()[0]

    finally:
        conn.close()

    assert count == 7

    print("测试6通过：七条温度采样已保存")


print("\n全部监控集成测试通过")
