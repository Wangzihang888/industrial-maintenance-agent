
from unittest.mock import patch

from app.nodes.ticket_node import (
    ticket_request_node,
    create_ticket_node,
)


INCIDENTS = {
    "INC-101": {
        "incident_id": "INC-101",
        "device_id": "RB-001",
        "incident_key": "encoder:communication",
        "alarm_code": "E-101",
        "created_at": "2026-10-14T10:00:00+00:00",
    },
    "INC-102": {
        "incident_id": "INC-102",
        "device_id": "RB-002",
        "incident_key": "servo:drive_fault",
        "alarm_code": "E-102",
        "created_at": "2026-10-14T10:01:00+00:00",
    },
    "INC-103": {
        "incident_id": "INC-103",
        "device_id": "RB-003",
        "incident_key": "temperature:overheat",
        "alarm_code": "E-103",
        "created_at": "2026-10-14T10:02:00+00:00",
    },
}


def build_state(incident_id, device_id):
    return {
        "execution_mode": "automatic",
        "incident_id": incident_id,
        "device_id": device_id,
        "trigger_risk_level": "critical",
        "need_ticket": True,
        "device_status": {
            "device_id": device_id,
            "temperature": 53.0,
            "current_alarm": None,
        },
    }


def main():
    # 替换数据库查询，避免操作正式数据库
    with patch(
        "app.nodes.ticket_node.IncidentStore"
    ) as mock_store_class:

        mock_store = mock_store_class.return_value
        mock_store.get_incident.side_effect = (
            lambda incident_id: INCIDENTS.get(incident_id)
        )

        for incident_id, device_id, alarm in [
            ("INC-101", "RB-001", "E-101"),
            ("INC-102", "RB-002", "E-102"),
            ("INC-103", "RB-003", "E-103"),
        ]:
            state = build_state(incident_id, device_id)

            result = ticket_request_node(state)
            request = result["ticket_request"]

            assert request["device_id"] == device_id
            assert request["alarm_code"] == alarm
            assert result["ticket_status"] == "pending_approval"

            print(f"通过：{alarm} 生成正确维修申请")

        # 当前设备无报警，但历史 Incident 是 E-101
        state = build_state("INC-101", "RB-001")
        state["device_status"]["current_alarm"] = "E-103"

        result = ticket_request_node(state)

        assert (
            result["ticket_request"]["alarm_code"]
            == "E-101"
        )

        print("通过：最新设备报警不会覆盖历史 Incident")

        # 人工未批准，不得调用正式创建工具
        with patch(
            "app.nodes.ticket_node.create_maintenance_ticket"
        ) as mock_ticket_tool:

            rejected = create_ticket_node({
                **state,
                "ticket_request": result["ticket_request"],
                "ticket_approved": False,
            })

            assert rejected["ticket_created"] is False
            assert rejected["ticket_status"] == "rejected"

            mock_ticket_tool.invoke.assert_not_called()

        print("通过：未经审批不会创建正式工单")

    print("\n多故障维修申请测试全部通过！")


if __name__ == "__main__":
    main()
