
"""
人工审批恢复集成回归测试。

测试实际业务组件：
- approval_node
- route_after_approval
- create_ticket_node
- resume_agent_approval
- TaskStore
- create_maintenance_ticket
- LangGraph SQLite Checkpointer

使用精简的真实 LangGraph 测试图。

隔离措施：
1. TaskStore 使用临时 SQLite
2. Checkpointer 使用临时 SQLite
3. 工单工具 DB_PATH 指向临时 SQLite
4. 不导入正式自动 Agent Graph
5. 不调用 LLM 或 RAG

不修改正式业务数据库。
"""

import importlib
import sqlite3
import sys
import types

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TypedDict
from unittest.mock import patch

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from app.nodes.approval_node import approval_node
from app.nodes.ticket_node import create_ticket_node
from app.routers.approval_router import route_after_approval
from app.tasks.task_store import TaskStore


# ============================================================
# 1. 测试专用 State
# ============================================================

class TestApprovalState(TypedDict, total=False):
    task_id: str
    incident_id: str
    execution_mode: str
    device_status: dict[str, Any]

    ticket_request: dict[str, Any]
    ticket_status: str
    ticket_approved: bool
    ticket_created: bool
    ticket_id: str | None


# ============================================================
# 2. 初始化临时正式工单表
# ============================================================

def init_maintenance_db(db_path: Path) -> None:

    connection = sqlite3.connect(db_path)

    try:
        with connection:
            connection.execute("""
                CREATE TABLE maintenance_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    alarm_code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
    finally:
        connection.close()


# ============================================================
# 3. 构建真实审批节点测试 Graph
# ============================================================

def build_test_graph(checkpointer):

    builder = StateGraph(TestApprovalState)

    builder.add_node(
        "approval",
        approval_node,
    )

    builder.add_node(
        "create_ticket",
        create_ticket_node,
    )

    builder.add_edge(
        START,
        "approval",
    )

    builder.add_conditional_edges(
        "approval",
        route_after_approval,
        {
            "create_ticket": "create_ticket",
            "end": END,
        },
    )

    builder.add_edge(
        "create_ticket",
        END,
    )

    return builder.compile(
        checkpointer=checkpointer
    )


# ============================================================
# 4. 安全导入真实 Approval Service
# ============================================================

def load_approval_service(test_graph):
    """
    approval_service.py 默认导入正式 graph。

    测试时将该依赖替换成测试 Graph，
    但仍执行真实的审批服务源码。
    """

    if "app.agent.graph" in sys.modules:
        raise RuntimeError(
            "正式 Agent Graph 已被导入，"
            "停止测试以避免默认数据库连接"
        )

    fake_graph_module = types.ModuleType(
        "app.agent.graph"
    )

    fake_graph_module.graph = test_graph

    with patch.dict(
        sys.modules,
        {"app.agent.graph": fake_graph_module},
    ):
        service = importlib.import_module(
            "app.tasks.approval_service"
        )

    return service


# ============================================================
# 5. 创建等待审批的测试任务
# ============================================================

def prepare_waiting_task(
    task_store,
    graph,
    incident_id,
    device_id,
    alarm_code,
):

    task = task_store.enqueue_task(
        incident_id=incident_id,
        device_id=device_id,
        risk_level="fault",
    )

    task_id = task["task_id"]

    assert task_store.claim_task(task_id)

    assert task_store.transition_task(
        task_id=task_id,
        expected_status="running",
        new_status="waiting_approval",
    )

    config = {
        "configurable": {
            "thread_id": task["thread_id"],
        }
    }

    initial_state = {
        "task_id": task_id,
        "incident_id": incident_id,
        "execution_mode": "automatic",
        "device_status": {
            "device_id": device_id,
            "current_alarm": alarm_code,
        },
        "ticket_request": {
            "device_id": device_id,
            "alarm_code": alarm_code,
            "title": f"{alarm_code} 测试维修申请",
            "description": "隔离环境人工审批测试",
        },
        "ticket_status": "pending_approval",
    }

    graph.invoke(
        initial_state,
        config=config,
    )

    snapshot = graph.get_state(config)

    interrupted = any(
        item.name == "approval"
        and bool(getattr(item, "interrupts", ()))
        for item in snapshot.tasks
    )

    assert interrupted, (
        "Graph 没有进入 HITL 审批暂停"
    )

    print(
        f"[PASS] {alarm_code} Graph 进入审批等待"
    )

    return task


# ============================================================
# 6. 查询工单数量
# ============================================================

def count_tickets(db_path: Path) -> int:

    connection = sqlite3.connect(db_path)

    try:
        return connection.execute(
            "SELECT COUNT(*) FROM maintenance_tickets"
        ).fetchone()[0]

    finally:
        connection.close()


# ============================================================
# 7. 主测试
# ============================================================

def main():

    with TemporaryDirectory(
        prefix="approval_resume_test_"
    ) as directory:

        folder = Path(directory)

        task_db = folder / "tasks.db"
        checkpoint_db = folder / "checkpoints.db"
        maintenance_db = folder / "maintenance.db"

        init_maintenance_db(maintenance_db)

        tasks = TaskStore(
            db_path=task_db
        )

        connection = sqlite3.connect(
            checkpoint_db,
            check_same_thread=False,
        )

        try:

            graph = build_test_graph(
                SqliteSaver(connection)
            )

            service = load_approval_service(
                graph
            )

            ticket_module = importlib.import_module(
                "app.tools.ticket_tool"
            )

            # 正式工单工具只写临时数据库
            with patch.object(
                ticket_module,
                "DB_PATH",
                maintenance_db,
            ):

                # ============================================
                # 场景 A：批准
                # ============================================

                approved_task = prepare_waiting_task(
                    task_store=tasks,
                    graph=graph,
                    incident_id="INC-APPROVE-001",
                    device_id="RB-001",
                    alarm_code="E-101",
                )

                approved_result = (
                    service.resume_agent_approval(
                        task_id=approved_task["task_id"],
                        approved=True,
                        task_store=tasks,
                    )
                )

                assert approved_result["resumed"] is True
                assert approved_result["status"] == "completed"
                assert approved_result["ticket_created"] is True
                assert approved_result["ticket_status"] == "created"
                assert approved_result["ticket_id"]

                assert count_tickets(maintenance_db) == 1

                print(
                    "[PASS] 审批通过后成功创建正式工单"
                )

                # ============================================
                # 场景 B：重复审批已完成任务
                # ============================================

                repeated = service.resume_agent_approval(
                    task_id=approved_task["task_id"],
                    approved=True,
                    task_store=tasks,
                )

                assert repeated["resumed"] is False
                assert (
                    repeated["reason"]
                    == "task_already_completed"
                )

                assert count_tickets(maintenance_db) == 1

                print(
                    "[PASS] 已完成任务重复审批被拦截"
                )

                # ============================================
                # 场景 C：拒绝
                # ============================================

                rejected_task = prepare_waiting_task(
                    task_store=tasks,
                    graph=graph,
                    incident_id="INC-REJECT-001",
                    device_id="RB-002",
                    alarm_code="E-102",
                )

                rejected_result = (
                    service.resume_agent_approval(
                        task_id=rejected_task["task_id"],
                        approved=False,
                        task_store=tasks,
                    )
                )

                assert rejected_result["resumed"] is True
                assert rejected_result["status"] == "completed"
                assert rejected_result["ticket_status"] == "rejected"
                assert rejected_result["ticket_created"] is False

                # 拒绝后工单数仍然为 1
                assert count_tickets(maintenance_db) == 1

                print(
                    "[PASS] 审批拒绝后没有创建正式工单"
                )

                # ============================================
                # 场景 D：TaskStore 状态
                # ============================================

                assert (
                    tasks.get_task(
                        approved_task["task_id"]
                    )["status"]
                    == "completed"
                )

                assert (
                    tasks.get_task(
                        rejected_task["task_id"]
                    )["status"]
                    == "completed"
                )

                print(
                    "[PASS] 审批结果与 TaskStore 状态一致"
                )

                # ============================================
                # 场景 E：Checkpoint 状态
                # ============================================

                for task, expected_approval in (
                    (approved_task, True),
                    (rejected_task, False),
                ):

                    snapshot = graph.get_state({
                        "configurable": {
                            "thread_id": task["thread_id"]
                        }
                    })

                    assert not snapshot.next
                    assert (
                        snapshot.values["ticket_approved"]
                        is expected_approval
                    )

                print(
                    "[PASS] 审批后 LangGraph Checkpoint 状态正确"
                )

                # ============================================
                # 场景 F：SQLite 完整性
                # ============================================

                db_paths = (
                    task_db,
                    checkpoint_db,
                    maintenance_db,
                )

                for db_path in db_paths:

                    check = sqlite3.connect(db_path)

                    try:
                        integrity = check.execute(
                            "PRAGMA integrity_check"
                        ).fetchone()[0]

                        assert integrity == "ok"

                    finally:
                        check.close()

                print(
                    "[PASS] 三个临时 SQLite 数据库完整性正常"
                )

        finally:
            # Windows 必须关闭连接后清理临时目录
            connection.close()

    print(
        "\n人工审批通过/拒绝集成测试全部通过！"
        "\n临时数据库已清理。"
    )


if __name__ == "__main__":
    main()
