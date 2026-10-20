
"""
E-103 温度业务回归测试（隔离通知副作用版）。

验证：
1. 温度 Warning 只通知，不申请工单
2. 温度 Critical 创建独立 Agent Task
3. 真实 LangGraph 调用 E-103 RAG
4. Critical 进入 HITL 人工审批
5. 未经审批不创建正式工单
6. 通知节点收到正确的 Task / Incident 关联标识

设备、Incident、Task 和 Checkpoint 使用临时 SQLite。
NotificationStore 使用 Mock 隔离，防止测试通知写入正式 notifications.db。
注意：此脚本验证通知节点的调用参数，不验证 NotificationStore 的真实持久化与去重。
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore
from app.monitoring.monitoring_engine import MonitoringEngine
from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore
from app.tasks.monitoring_task_adapter import enqueue_monitoring_events

from app.nodes.evaluate_node import decide_action_node
from app.nodes.notification_node import notification_node

from app.agent.graph import builder
import app.tasks.agent_runner as runner


def check_rag(messages):
    """检查本次 Agent 是否实际获得 E-103 维修知识库证据。"""
    matched = []

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue

        try:
            data = json.loads(message.content)
        except (TypeError, ValueError):
            continue

        if not isinstance(data, dict):
            continue

        if (
            data.get("result_type") == "fault_knowledge"
            and data.get("alarm_code") == "E-103"
            and data.get("success") is True
        ):
            matched.extend(data.get("knowledge") or [])

    assert matched, "Agent 没有获得有效的 E-103 RAG 证据"
    assert all(
        isinstance(item, dict) and item.get("alarm_code") == "E-103"
        for item in matched
    ), "RAG 混入了其他故障章节"

    print(f"[PASS] 真实 Agent 检索 E-103，获得 {len(matched)} 条匹配证据")


def main():
    now = datetime.now(timezone.utc)

    with TemporaryDirectory() as directory:
        folder = Path(directory)

        # 1. 各业务库与正式项目数据隔离。
        state_store = DeviceStateStore(folder / "states.db")
        incident_store = IncidentStore(folder / "incidents.db")
        task_store = TaskStore(folder / "tasks.db")

        engine = MonitoringEngine(
            state_store=state_store,
            incident_store=incident_store,
        )

        # 2. Mock 只负责拦截 NotificationStore 写入，不伪造 Agent 或 RAG 结果。
        with patch("app.nodes.notification_node.NotificationStore") as notification_store_class:
            notification_store = notification_store_class.return_value

            # 第一次采样：68℃，进入 Warning。
            warning_snapshot = DeviceSnapshot(
                device_id="RB-003",
                temperature=68.0,
                sampled_at=now,
            )
            warning_result = engine.process_snapshot(
                snapshot=warning_snapshot,
                warning=65.0,
                limit=75.0,
            )
            warning_tasks = enqueue_monitoring_events(
                monitoring_result=warning_result,
                task_store=task_store,
            )

            assert warning_result["risk_level"] == "warning"
            assert warning_result["events"][0]["risk_level"] == "warning"
            assert warning_tasks[0]["task"]["risk_level"] == "warning"

            warning_incident_id = warning_result["events"][0]["incident_id"]
            warning_task_id = warning_tasks[0]["task"]["task_id"]

            warning_state = {
                "execution_mode": "automatic",
                "device_id": "RB-003",
                "incident_id": warning_incident_id,
                "task_id": warning_task_id,  # 自动通知节点要求此标识。
                "trigger_risk_level": "warning",
                "device_status": {
                    "device_id": "RB-003",
                    "device_name": "装配机器人3号",
                    "temperature": 68.0,
                    "temperature_warning": 65.0,
                    "temperature_limit": 75.0,
                },
            }
            warning_state.update(decide_action_node(warning_state))

            assert warning_state["need_notification"] is True
            assert warning_state["need_ticket"] is False
            assert warning_state["notification_level"] == "warning"

            with patch(
                "app.nodes.notification_node.IncidentStore",
                return_value=incident_store,
            ):
                notice = notification_node(warning_state)["notification_message"]

            assert "WARNING" in notice
            assert "68.0" in notice
            assert "None℃" not in notice

            notification_store.save_notification.assert_called_once()
            warning_notice_args = notification_store.save_notification.call_args.kwargs
            assert warning_notice_args["task_id"] == warning_task_id
            assert warning_notice_args["incident_id"] == warning_incident_id
            assert warning_notice_args["notification_level"] == "warning"
            print("[PASS] Warning 仅通知、不申请工单，且通知关联正确")
            print("预警通知：", notice)

            # 分离 Warning 与 Critical 的持久化调用断言。
            notification_store.save_notification.reset_mock()

            # 3. 第二次采样：82℃，同一 Incident 升级为 Critical。
            critical_snapshot = DeviceSnapshot(
                device_id="RB-003",
                temperature=82.0,
                current_alarm="E-103",
                sampled_at=now + timedelta(seconds=2),
            )
            critical_result = engine.process_snapshot(
                snapshot=critical_snapshot,
                warning=65.0,
                limit=75.0,
            )
            critical_tasks = enqueue_monitoring_events(
                monitoring_result=critical_result,
                task_store=task_store,
            )

            event = critical_result["events"][0]
            task = critical_tasks[0]["task"]

            assert event["alarm_code"] == "E-103"
            assert event["risk_level"] == "critical"
            assert event["risk_escalated"] is True
            assert task["risk_level"] == "critical"
            assert task["created"] is True
            assert event["incident_id"] == warning_incident_id
            assert task["task_id"] != warning_task_id
            print("[PASS] 82℃ 同 Incident 升级 Critical，并建立独立处置任务")

            # 4. LangGraph 使用单独临时 Checkpoint，确保不会污染正式会话。
            connection = sqlite3.connect(
                folder / "checkpoints.db",
                check_same_thread=False,
            )

            try:
                test_graph = builder.compile(
                    checkpointer=SqliteSaver(connection)
                )

                # 5. 自动任务及业务节点查询相同的临时 Incident。
                with (
                    patch.object(runner, "graph", test_graph),
                    patch.object(
                        runner,
                        "IncidentStore",
                        return_value=incident_store,
                    ),
                    patch(
                        "app.nodes.notification_node.IncidentStore",
                        return_value=incident_store,
                    ),
                    patch(
                        "app.nodes.ticket_node.IncidentStore",
                        return_value=incident_store,
                    ),
                ):
                    result = runner.run_agent_task(
                        task_id=task["task_id"],
                        task_store=task_store,
                    )

                    assert result["started"] is True
                    assert result["status"] == "waiting_approval"
                    assert result["risk_level"] == "critical"
                    assert result["alarm_code"] == "E-103"
                    print("[PASS] E-103 Agent 进入 HITL 审批暂停")

                    config = {
                        "configurable": {
                            "thread_id": task["thread_id"],
                        }
                    }
                    snapshot = test_graph.get_state(config)
                    state = snapshot.values

                    check_rag(state.get("messages", []))

                    notification = state.get("notification_message", "")
                    assert "CRITICAL" in notification
                    assert "E-103" in notification
                    assert "None℃" not in notification
                    print("[PASS] E-103 Critical 通知内容正确")

                    # NotificationStore 已 Mock，无正式通知数据库写入。
                    notification_store.save_notification.assert_called_once()
                    critical_notice_args = notification_store.save_notification.call_args.kwargs
                    assert critical_notice_args["task_id"] == task["task_id"]
                    assert critical_notice_args["incident_id"] == event["incident_id"]
                    assert critical_notice_args["notification_level"] == "critical"
                    print("[PASS] Critical 通知关联 Task / Incident 正确")

                    request = state.get("ticket_request") or {}
                    assert request.get("device_id") == "RB-003"
                    assert request.get("alarm_code") == "E-103"
                    assert state.get("ticket_status") == "pending_approval"
                    print("[PASS] 生成正确的 E-103 维修申请")

                    assert state.get("ticket_approved") is not True
                    assert state.get("ticket_created") is not True
                    assert state.get("ticket_id") is None
                    print("[PASS] 未经审批，不创建正式工单")

                saved_task = task_store.get_task(task["task_id"])
                assert saved_task["status"] == "waiting_approval"

            finally:
                connection.close()

    print("\nE-103 温度回归测试全部通过！")


if __name__ == "__main__":
    main()
