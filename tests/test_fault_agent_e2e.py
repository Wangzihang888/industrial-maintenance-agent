
"""
E-101 / E-102 真实 Agent 端到端回归测试。

测试内容：
1. 创建临时 Incident 和 Agent Task
2. 真实执行 LangGraph、LLM Tool Calling 和 RAG
3. 验证故障知识证据
4. 验证通知及维修申请
5. 验证 HITL 审批暂停
6. 验证未经审批不创建正式维修工单

安全措施：
- 业务 SQLite 数据库使用临时路径
- 项目默认 SQLite 连接重定向到临时目录
- 正式通知写入使用 Mock
- 正式工单创建使用 Mock
- 测试结束关闭全部测试相关 Checkpoint 连接

注意：
本测试会调用真实 LLM/RAG，可能产生 API 费用。
"""

import argparse
import importlib
import json
import sqlite3
import sys

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore


# ============================================================
# 1. 测试故障配置
# ============================================================

CASES = {
    "E-101": {
        "device_id": "RB-001",
        "incident_key": "encoder:communication",
    },
    "E-102": {
        "device_id": "RB-002",
        "incident_key": "servo:drive_fault",
    },
}


# ============================================================
# 2. 检查真实 RAG 工具证据
# ============================================================

def check_rag_evidence(messages, alarm_code):

    rag_results = []

    for message in messages:

        if not isinstance(message, ToolMessage):
            continue

        try:
            data = json.loads(message.content)
        except (TypeError, ValueError):
            continue

        if (
            isinstance(data, dict)
            and data.get("result_type") == "fault_knowledge"
        ):
            rag_results.append(data)

    assert rag_results, (
        f"{alarm_code} 没有调用 RAG 工具"
    )

    successful = [
        result
        for result in rag_results
        if result.get("success") is True
        and result.get("alarm_code") == alarm_code
        and result.get("knowledge")
    ]

    assert successful, (
        f"{alarm_code} 没有取得有效 RAG 证据"
    )

    knowledge = successful[-1]["knowledge"]

    assert all(
        item.get("alarm_code") == alarm_code
        for item in knowledge
    ), "RAG 证据混入其他故障章节"

    print(
        f"通过：{alarm_code} 实际调用 RAG，"
        f"获得 {len(knowledge)} 条匹配证据"
    )


# ============================================================
# 3. 执行单个故障测试
# ============================================================

def run_case(
    alarm_code,
    agent_runner,
    notification_module,
    ticket_module,
):

    case = CASES[alarm_code]

    with TemporaryDirectory() as directory:

        folder = Path(directory)

        # ----------------------------------------------------
        # 3.1 临时业务数据库
        # ----------------------------------------------------

        incidents = IncidentStore(
            db_path=folder / "incidents.db"
        )

        tasks = TaskStore(
            db_path=folder / "tasks.db"
        )

        # ----------------------------------------------------
        # 3.2 创建 Incident
        # ----------------------------------------------------

        incident = incidents.record_anomaly(
            device_id=case["device_id"],
            risk_level="fault",
            alarm_code=alarm_code,
            incident_key=case["incident_key"],
        )

        # ----------------------------------------------------
        # 3.3 创建 Agent Task
        # ----------------------------------------------------

        task = tasks.enqueue_task(
            incident_id=incident["incident_id"],
            device_id=case["device_id"],
            risk_level="fault",
        )

        assert task["created"] is True
        assert task["status"] == "pending"

        print(f"\n测试故障：{alarm_code}")
        print(f"测试 Incident：{incident['incident_id']}")
        print(f"测试 Task：{task['task_id']}")

        # ----------------------------------------------------
        # 3.4 创建独立 Checkpointer
        # ----------------------------------------------------

        connection = sqlite3.connect(
            folder / "checkpoints.db",
            check_same_thread=False,
        )

        try:

            graph_module = importlib.import_module(
                "app.agent.graph"
            )

            test_graph = graph_module.builder.compile(
                checkpointer=SqliteSaver(connection)
            )

            # ------------------------------------------------
            # 3.5 Mock 业务写入
            # ------------------------------------------------

            with (
                patch.object(
                    agent_runner,
                    "graph",
                    test_graph,
                ),
                patch.object(
                    agent_runner,
                    "IncidentStore",
                    return_value=incidents,
                ),
                patch.object(
                    notification_module,
                    "IncidentStore",
                    return_value=incidents,
                ),
                patch.object(
                    ticket_module,
                    "IncidentStore",
                    return_value=incidents,
                ),
                patch.object(
                    notification_module,
                    "NotificationStore",
                ) as notification_store_class,
                patch.object(
                    ticket_module,
                    "create_maintenance_ticket",
                ) as create_ticket_tool,
            ):

                # --------------------------------------------
                # 3.6 执行真实 Agent
                # --------------------------------------------

                result = agent_runner.run_agent_task(
                    task_id=task["task_id"],
                    task_store=tasks,
                )

                print(
                    "Agent 执行状态：",
                    result["status"],
                )

                # --------------------------------------------
                # 3.7 验证 HITL
                # --------------------------------------------

                assert result["started"] is True

                assert (
                    result["status"] == "waiting_approval"
                )

                saved_task = tasks.get_task(
                    task["task_id"]
                )

                assert saved_task["risk_level"] == "fault"

                assert (
                    saved_task["status"]
                    == "waiting_approval"
                )

                print(
                    "通过：fault 任务进入 HITL 审批暂停"
                )

                # --------------------------------------------
                # 3.8 获取 Graph State
                # --------------------------------------------

                config = {
                    "configurable": {
                        "thread_id": task["thread_id"],
                    }
                }

                snapshot = test_graph.get_state(config)

                state = snapshot.values

                # --------------------------------------------
                # 3.9 检查真实 RAG
                # --------------------------------------------

                check_rag_evidence(
                    state.get("messages", []),
                    alarm_code,
                )

                # --------------------------------------------
                # 3.10 验证通知
                # --------------------------------------------

                notification = state.get(
                    "notification_message",
                    "",
                )

                assert alarm_code in notification

                assert "CRITICAL" not in notification

                assert "None℃" not in notification

                print(
                    "通过：通知没有错误的温度 Critical"
                )

                # --------------------------------------------
                # 3.11 检查通知持久化调用
                # --------------------------------------------

                notification_store_class.return_value.save_notification.assert_called_once_with(
                    task_id=task["task_id"],
                    incident_id=incident["incident_id"],
                    device_id=case["device_id"],
                    notification_level="fault",
                    message=notification,
                )

                print(
                    "通过：通知持久化参数正确，"
                    "且已通过 Mock 隔离"
                )

                # --------------------------------------------
                # 3.12 验证维修申请
                # --------------------------------------------

                request = (
                    state.get("ticket_request") or {}
                )

                assert (
                    request.get("device_id")
                    == case["device_id"]
                )

                assert (
                    request.get("alarm_code")
                    == alarm_code
                )

                assert (
                    state.get("ticket_status")
                    == "pending_approval"
                )

                print(
                    "通过：维修申请与 Incident 匹配"
                )

                # --------------------------------------------
                # 3.13 未审批不得创建正式工单
                # --------------------------------------------

                assert (
                    state.get("ticket_approved") is not True
                )

                assert (
                    state.get("ticket_created") is not True
                )

                assert state.get("ticket_id") is None

                create_ticket_tool.invoke.assert_not_called()

                print(
                    "通过：尚未批准，"
                    "未进入正式工单创建状态"
                )

                print(
                    f"\n{alarm_code} 端到端业务断言全部通过！"
                )

        finally:
            # 先关闭本次测试的 Checkpointer
            # 避免 Windows 临时文件被占用
            connection.close()


# ============================================================
# 4. 主程序
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--alarm",
        choices=["E-101", "E-102"],
        required=True,
    )

    args = parser.parse_args()

    project_data = (
        Path(__file__).resolve().parents[1] / "data"
    ).resolve()

    checkpoint_default = (
        project_data / "langgraph_checkpoints.db"
    ).resolve()

    real_connect = sqlite3.connect

    # --------------------------------------------------------
    # 4.1 临时数据库保护环境
    # --------------------------------------------------------

    with TemporaryDirectory(
        prefix="industrial_e2e_guard_"
    ) as temp:

        snapshots = Path(temp) / "database_snapshots"
        snapshots.mkdir()

        # ----------------------------------------------------
        # 4.2 拦截项目默认 SQLite 连接
        # ----------------------------------------------------

        def guarded_connect(
            database,
            *args,
            **kwargs,
        ):

            if (
                isinstance(database, (str, Path))
                and str(database) != ":memory:"
            ):

                database_path = Path(database).resolve()

                if database_path.is_relative_to(
                    project_data
                ):

                    relative = database_path.relative_to(
                        project_data
                    )

                    isolated_path = snapshots / relative

                    isolated_path.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    # 普通业务库：从正式库读取快照
                    # 后续所有写入都发生在临时副本中
                    if (
                        database_path != checkpoint_default
                        and not isolated_path.exists()
                        and database_path.exists()
                    ):

                        source_uri = (
                            database_path.as_uri()
                            + "?mode=ro"
                        )

                        source = real_connect(
                            source_uri,
                            uri=True,
                            timeout=10,
                        )

                        try:

                            destination = real_connect(
                                isolated_path,
                                timeout=10,
                            )

                            try:
                                source.backup(destination)
                            finally:
                                destination.close()

                        finally:
                            source.close()

                    # 默认 Checkpoint 使用独立临时库
                    database = isolated_path

            return real_connect(
                database,
                *args,
                **kwargs,
            )

        # ----------------------------------------------------
        # 4.3 启用 SQLite 隔离
        # ----------------------------------------------------

        with patch(
            "sqlite3.connect",
            side_effect=guarded_connect,
        ):

            try:

                # 这些模块在隔离环境下导入
                import app.tasks.agent_runner as agent_runner

                import app.nodes.notification_node as notification_module

                import app.nodes.ticket_node as ticket_module

                # --------------------------------------------
                # 4.4 执行测试
                # --------------------------------------------

                run_case(
                    args.alarm,
                    agent_runner=agent_runner,
                    notification_module=notification_module,
                    ticket_module=ticket_module,
                )

            finally:

                # ============================================
                # 关键修复：
                # 关闭 graph.py 导入时创建的全局连接。
                #
                # 必须在 TemporaryDirectory 删除临时文件前
                # 执行，否则 Windows 会报 WinError 32。
                # ============================================

                graph_module = sys.modules.get(
                    "app.agent.graph"
                )

                if graph_module is not None:

                    global_connection = getattr(
                        graph_module,
                        "checkpoint_connection",
                        None,
                    )

                    if global_connection is not None:

                        global_connection.close()

                        print(
                            "通过：已关闭 Graph 默认 "
                            "Checkpoint 数据库连接"
                        )

    print(
        "\n测试结束：临时数据库清理完成，"
        "未写入项目正式业务数据库。"
    )


# ============================================================
# 5. 程序入口
# ============================================================

if __name__ == "__main__":
    main()
