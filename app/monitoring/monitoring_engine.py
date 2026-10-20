
from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore
from app.incidents.incident_store import IncidentStore


def classify_temperature(
    temperature: float,
    warning: float,
    limit: float,
) -> str:
    """只根据温度和阈值判断温度状态。"""

    if warning >= limit:
        raise ValueError("预警阈值必须低于安全限制阈值")

    if temperature < warning:
        return "normal"

    if temperature <= limit:
        return "warning"

    return "critical"


class MonitoringEngine:

    def __init__(
        self,
        state_store: DeviceStateStore,
        incident_store: IncidentStore,
    ):
        self.state_store = state_store
        self.incident_store = incident_store

    def process_snapshot(
        self,
        snapshot: DeviceSnapshot,
        warning: float,
        limit: float,
    ) -> dict:
        """
        一次采样可以产生多个独立故障事件。

        E-101 / E-102 使用 fault。
        温度异常继续使用 warning / critical。
        """

        temperature_risk = classify_temperature(
            snapshot.temperature,
            warning,
            limit,
        )

        saved = self.state_store.save_snapshot(snapshot)

        # 原有顶层字段保留温度语义，供旧接口兼容。
        result = {
            "device_id": snapshot.device_id,
            "risk_level": temperature_risk,
            "should_trigger": False,
            "incident_id": None,
            "created_incident": False,
            "risk_escalated": False,
            "ignored": not saved["latest_updated"],
            "reason": "no_anomaly",
            "events": [],
        }

        # 重复或旧采样不能再次触发业务事件。
        if not saved["latest_updated"]:
            result["reason"] = "duplicate_or_stale_snapshot"
            return result

        # 元组：故障关联键、报警代码、处置类别
        faults = []

        # E-101：编码器连续通信失败
        if (
            snapshot.device_id in {"RB-001", "RB-002", "RB-003"}
            and not snapshot.encoder_comm_ok
            and snapshot.encoder_error_count >= 3
        ):
            faults.append((
                "encoder:communication",
                "E-101",
                "fault",
            ))

        # E-102：伺服驱动器报告故障
        if (
            snapshot.device_id in {"RB-001", "RB-002", "RB-003"}
            and snapshot.servo_drive_status == "fault"
        ):
            faults.append((
                "servo:drive_fault",
                "E-102",
                "fault",
            ))

        # 温度异常：保留已有分级。
        if temperature_risk != "normal":

            # 只有采样明确报告 E-103，才记录该代码。
            temperature_alarm = (
                "E-103"
                if snapshot.current_alarm == "E-103"
                else None
            )

            faults.append((
                "temperature:overheat",
                temperature_alarm,
                temperature_risk,
            ))

        # 每种故障独立保存 Incident。
        for incident_key, alarm_code, risk_level in faults:

            incident_result = self.incident_store.record_anomaly(
                device_id=snapshot.device_id,
                incident_key=incident_key,
                alarm_code=alarm_code,
                risk_level=risk_level,
            )

            event = {
                "device_id": snapshot.device_id,
                "incident_key": incident_key,
                "alarm_code": alarm_code,
                "risk_level": risk_level,
                "incident_id": incident_result["incident_id"],
                "should_trigger": incident_result["should_trigger"],
                "created_incident": incident_result["created_incident"],
                "risk_escalated": incident_result["risk_escalated"],
            }

            result["events"].append(event)

            # 兼容旧的单温度接口。
            if incident_key == "temperature:overheat":
                result.update({
                    "risk_level": risk_level,
                    "should_trigger": event["should_trigger"],
                    "incident_id": event["incident_id"],
                    "created_incident": event["created_incident"],
                    "risk_escalated": event["risk_escalated"],
                })

        if not faults:
            result["reason"] = "normal_state"

        elif any(
            event["should_trigger"]
            for event in result["events"]
        ):
            result["reason"] = "new_or_escalated_anomaly"

        else:
            result["reason"] = "ongoing_anomaly"

        return result
