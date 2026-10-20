
from pathlib import Path
from tempfile import TemporaryDirectory

from app.incidents.incident_store import IncidentStore


def main():
    # 使用临时数据库，不影响项目已有 Incident
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "incidents.db"
        store = IncidentStore(db_path=db_path)

        # 1. RB-001：首次出现 E-101
        e101 = store.record_anomaly(
            device_id="RB-001",
            risk_level="fault",
            alarm_code="E-101",
            incident_key="encoder:communication",
        )

        assert e101["created_incident"] is True
        assert e101["should_trigger"] is True

        print("通过：E-101 创建独立 Incident")

        # 2. 同一设备继续发生 E-101，不能重复创建
        repeated = store.record_anomaly(
            device_id="RB-001",
            risk_level="fault",
            alarm_code="E-101",
            incident_key="encoder:communication",
        )

        assert repeated["incident_id"] == e101["incident_id"]
        assert repeated["created_incident"] is False
        assert repeated["should_trigger"] is False

        print("通过：持续 E-101 不重复触发")

        # 3. 同一设备发生 E-102，必须新建 Incident
        e102 = store.record_anomaly(
            device_id="RB-001",
            risk_level="fault",
            alarm_code="E-102",
            incident_key="servo:drive_fault",
        )

        assert e102["incident_id"] != e101["incident_id"]

        print("通过：同一设备 E-101 和 E-102 相互独立")

        # 4. 温度异常仍使用原来的默认故障键
        warning = store.record_anomaly(
            device_id="RB-001",
            risk_level="warning",
            alarm_code=None,
        )

        assert warning["created_incident"] is True

        # 5. Warning 升级为 Critical
        critical = store.record_anomaly(
            device_id="RB-001",
            risk_level="critical",
            alarm_code="E-103",
        )

        assert critical["incident_id"] == warning["incident_id"]
        assert critical["risk_escalated"] is True
        assert critical["should_trigger"] is True

        print("通过：温度 Warning 升级 Critical")

        # 6. 三种故障能够分别查询
        assert store.get_active_incident(
            "RB-001", "encoder:communication"
        )["incident_id"] == e101["incident_id"]

        assert store.get_active_incident(
            "RB-001", "servo:drive_fault"
        )["incident_id"] == e102["incident_id"]

        assert store.get_active_incident(
            "RB-001"
        )["incident_id"] == warning["incident_id"]

        print("通过：三种故障分别查询")

        # 7. 关闭 E-101，不应影响其他故障
        assert store.close_incident(e101["incident_id"]) is True

        assert store.get_active_incident(
            "RB-001", "encoder:communication"
        ) is None

        assert store.get_active_incident(
            "RB-001", "servo:drive_fault"
        ) is not None

        print("通过：关闭 E-101 不影响 E-102")

        print("\n全部多故障 Incident 测试通过！")


if __name__ == "__main__":
    main()
