
from app.nodes.evaluate_node import (
    decide_action,
    decide_action_node,
)


def main():

    # E-101 / E-102：故障类别 fault
    result = decide_action_node({
        "execution_mode": "automatic",
        "trigger_risk_level": "fault",
    })

    assert result == {
        "need_notification": True,
        "need_ticket": True,
        "notification_level": "fault",
    }

    print("通过：E-101/E-102 使用 fault 处置")

    # 温度 Warning：只通知
    warning = decide_action("warning")

    assert warning["need_notification"] is True
    assert warning["need_ticket"] is False

    print("通过：温度 Warning 不申请工单")

    # 温度 Critical：需要维修审批
    critical = decide_action("critical")

    assert critical["need_notification"] is True
    assert critical["need_ticket"] is True
    assert critical["notification_level"] == "critical"

    print("通过：温度 Critical 进入维修流程")

    # Normal：无动作
    normal = decide_action("normal")

    assert normal["need_notification"] is False
    assert normal["need_ticket"] is False

    print("通过：Normal 不触发处置")

    # 不允许未知业务类别
    try:
        decide_action("unknown")
    except ValueError:
        print("通过：未知类别不会静默放行")
    else:
        raise AssertionError("应当拒绝未知类别")

    print("\nAgent 业务动作决策测试全部通过！")


if __name__ == "__main__":
    main()
