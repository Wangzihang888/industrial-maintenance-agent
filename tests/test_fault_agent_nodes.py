
from unittest.mock import patch

from app.nodes.evaluate_node import decide_action_node
from app.nodes.notification_node import notification_node
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
        "created_at": "2026-10-15T10:00:00+00:00",
    },
    "INC-102": {
        "incident_id": "INC-102",
        "device_id": "RB-002",
        "incident_key": "servo:drive_fault",
        "alarm_code": "E-102",
        "created_at": "2026-10-15T10:00:00+00:00",
    },
    "INC-103": {
        "incident_id": "INC-103",
        "device_id": "RB-003",
        "incident_key": "temperature:overheat",
        "alarm_code": "E-103",
        "created_at": "2026-10-15T10:00:00+00:00",
    },
}


def main():
    with (
        patch("app.nodes.notification_node.IncidentStore") as notify_store,
        patch("app.nodes.ticket_node.IncidentStore") as ticket_store,
        patch("app.nodes.ticket_node.create_maintenance_ticket") as tool,
        patch("app.nodes.notification_node.NotificationStore") as notification_store_class,
    ):
        lookup = lambda incident_id: INCIDENTS.get(incident_id)
        notify_store.return_value.get_incident.side_effect = lookup
        ticket_store.return_value.get_incident.side_effect = lookup

        for code, incident_id, device_id, level in [
            ("E-101", "INC-101", "RB-001", "fault"),
            ("E-102", "INC-102", "RB-002", "fault"),
            ("E-103", "INC-103", "RB-003", "critical"),
        ]:
            state = {
                "execution_mode": "automatic",
                "incident_id": incident_id,
                "task_id": f"TEST-TASK-{code}",
                "device_id": device_id,
                "trigger_risk_level": level,
                "device_status": {
                    "device_id": device_id,
                    "device_name": device_id,
                    "temperature": 53.0,
                    "current_alarm": "E-999",
                },
            }

            decision = decide_action_node(state)
            state.update(decision)

            assert state["need_notification"] is True
            assert state["need_ticket"] is True

            notice = notification_node(state)[
                "notification_message"
            ]

            assert code in notice
            assert "None℃" not in notice

            # 使用 Mock 验证写入参数，不连接真实通知数据库。
            notification_store_class.return_value.save_notification.assert_called_once_with(
                task_id=state["task_id"],
                incident_id=incident_id,
                device_id=device_id,
                notification_level=level,
                message=notice,
            )
            notification_store_class.return_value.save_notification.reset_mock()

            if level == "fault":
                assert "CRITICAL" not in notice

            request = ticket_request_node(state)[
                "ticket_request"
            ]

            assert request["alarm_code"] == code
            assert request["device_id"] == device_id

            # 未经人工批准，不允许调用正式创建工具
            rejected = create_ticket_node({
                **state,
                "ticket_request": request,
                "ticket_approved": False,
            })

            assert rejected["ticket_created"] is False
            tool.invoke.assert_not_called()

            print(f"通过：{code} 决策、通知、申请及审批拦截")

        print("\n多故障 Agent 节点测试全部通过！")


if __name__ == "__main__":
    main()
