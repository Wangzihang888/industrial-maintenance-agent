
from unittest.mock import patch

from app.nodes.notification_node import (
    notification_node,
)


INCIDENT = {
    "incident_id": "INC-TEST-103",
    "device_id": "RB-003",
    "incident_key": "temperature:overheat",
    "alarm_code": "E-103",
}


def make_state(trigger_level, current_temperature):
    return {
        "execution_mode": "automatic",
        "task_id": f"TASK-TEST-{trigger_level}",
        "incident_id": "INC-TEST-103",
        "device_id": "RB-003",
        "trigger_risk_level": trigger_level,
        "notification_level": trigger_level,
        "need_notification": True,
        "device_status": {
            "device_id": "RB-003",
            "device_name": "装配机器人3号",
            "temperature": current_temperature,
            "temperature_warning": 65.0,
            "temperature_limit": 75.0,
        },
    }


def main():
    with (
        patch(
            "app.nodes.notification_node.IncidentStore"
        ) as incident_store,
        patch(
            "app.nodes.notification_node.NotificationStore"
        ) as notification_store,
    ):

        incident_store.return_value.get_incident.return_value = (
            INCIDENT
        )

        # Warning 触发后，当前温度已升至 Critical
        warning = notification_node(
            make_state("warning", 75.5)
        )["notification_message"]

        assert "WARNING 事件触发" in warning
        assert "75.5℃" in warning
        assert "已超过安全限值" in warning

        print("通过：Warning 触发与查询时 Critical 正确区分")
        print(warning)
        print()

        # Critical 触发，查询时仍然过温
        critical = notification_node(
            make_state("critical", 82.0)
        )["notification_message"]

        assert "CRITICAL 事件触发" in critical
        assert "82.0℃" in critical
        assert "已超过安全限值" in critical

        print("通过：Critical 通知正确")
        print(critical)
        print()

        # Critical 触发后，查询时温度已经恢复
        recovered = notification_node(
            make_state("critical", 53.0)
        )["notification_message"]

        assert "CRITICAL 事件触发" in recovered
        assert "已低于预警阈值" in recovered

        print("通过：历史 Critical 与当前恢复状态正确区分")

        # 验证通知仍按 Task 触发类别保存
        assert notification_store.return_value.save_notification.call_count == 3

        first_call = (
            notification_store.return_value
            .save_notification.call_args_list[0]
        )

        assert (
            first_call.kwargs["notification_level"]
            == "warning"
        )

        print("通过：通知持久化保留任务触发类别")

    print("\n温度通知语义测试全部通过！")


if __name__ == "__main__":
    main()
