
"""
LangGraph 审批 Checkpoint 持久化恢复测试。

验证：
1. Graph 进入 HITL 审批等待
2. 第一次 Checkpoint 数据库连接关闭
3. 重新打开 SQLite 并重新编译 Graph
4. 从同一 thread_id 恢复审批
5. 创建正式工单
6. TaskStore、Checkpoint 和工单状态一致
7. 重复审批不会产生第二张工单

安全原则：
所有 SQLite 数据库均位于 TemporaryDirectory。
不导入真实自动 Agent Graph。
不调用 LLM / RAG。
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
# 1. 测试 State
# ============================================================

class ApprovalState(TypedDict, total=False):
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
# 2. 构建审批 Graph
# ============================================================

def build_graph(connection):

    builder = StateGraph(ApprovalState)

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
        checkpointer=SqliteSaver(connection)
    )


# ============================================================
# 3. 初始化临时工单数据库
# ============================================================

def init_maintenance_db(db_path):

    with sqlite3.connect(db_path) as conn:

        conn.execute("""
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


# ============================================================
# 4. 安全加载真实审批服务
# ============================================================

def load_service(graph):

    if (
        "app.agent.graph" in sys.modules
        or "app.tasks.approval_service" in sys.modules
    ):
        raise RuntimeError(
            "检测到审批服务或正式 Agent Graph "
            "已提前加载，为确保隔离而停止测试"
        )

    fake_module = types.ModuleType(
        "app.agent.graph"
    )

    fake_module.graph = graph

    with patch.dict(
        sys.modules,
        {"app.agent.graph": fake_module},
    ):
        service = importlib.import_module(
            "app.tasks.approval_service"
        )

    return service


# ============================================================
# 5. 数据库查询工具
# ============================================================

def count_tickets(db_path):

    with sqlite3.connect(db_path) as conn:

        return conn.execute(
            "SELECT COUNT(*) FROM maintenance_tickets"
        ).fetchone()[0]


def check_integrity(db_path):

    with sqlite3.connect(db_path) as conn:

        result = conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

    assert result == "ok", (
        f"{db_path.name} 数据完整性失败：{result}"
    )


# ============================================================
# 6. 主测试
# ============================================================

def main():

    with TemporaryDirectory(
        prefix="checkpoint_recovery_test_"
    ) as directory:

        folder = Path(directory)

        task_db = folder / "tasks.db"
        checkpoint_db = folder / "checkpoints.db"
        maintenance_db = folder / "maintenance.db"

        init_maintenance_db(maintenance_db)

        task_store = TaskStore(
            db_path=task_db
        )

        # ----------------------------------------------------
        # 6.1 创建临时任务
        # ----------------------------------------------------

        task = task_store.enqueue_task(
            incident_id="INC-RECOVERY-001",
            device_id="RB-001",
            risk_level="fault",
        )

        assert task["created"] is True

        assert task_store.claim_task(
            task["task_id"]
        )

        config = {
            "configurable": {
                "thread_id": task["thread_id"],
            }
        }

        # ----------------------------------------------------
        # 6.2 第一次 Graph 启动
        # ----------------------------------------------------

        connection1 = sqlite3.connect(
            checkpoint_db,
            check_same_thread=False,
        )

        try:

            graph1 = build_graph(connection1)

            initial_state = {
                "task_id": task["task_id"],
                "incident_id": task["incident_id"],
                "execution_mode": "automatic",
                "device_status": {
                    "device_id": "RB-001",
                    "current_alarm": "E-101",
                },
                "ticket_request": {
                    "device_id": "RB-001",
                    "alarm_code": "E-101",
                    "title": "E-101 编码器故障维修申请",
                    "description": "Checkpoint 恢复测试",
                },
                "ticket_status": "pending_approval",
            }

            graph1.invoke(
                initial_state,
                config=config,
            )

            before = graph1.get_state(config)

            interrupted = any(
                item.name == "approval"
                and bool(
                    getattr(item, "interrupts", ())
                )
                for item in before.tasks
            )

            assert interrupted

            assert before.values["task_id"] == task["task_id"]

            assert task_store.transition_task(
                task_id=task["task_id"],
                expected_status="running",
                new_status="waiting_approval",
            )

            print(
                "[PASS] 第一次 Graph 进入 HITL 审批等待"
            )

        finally:

            connection1.close()

        print(
            "[PASS] 第一次 Checkpoint 连接已关闭"
        )

        # ----------------------------------------------------
        # 6.3 模拟重启：重新连接和编译
        # ----------------------------------------------------

        connection2 = sqlite3.connect(
            checkpoint_db,
            check_same_thread=False,
        )

        try:

            graph2 = build_graph(connection2)

            recovered = graph2.get_state(config)

            recovered_interrupt = any(
                item.name == "approval"
                and bool(
                    getattr(item, "interrupts", ())
                )
                for item in recovered.tasks
            )

            assert recovered_interrupt, (
                "重新连接后未恢复 HITL Interrupt"
            )

            assert (
                recovered.values["task_id"]
                == task["task_id"]
            )

            assert (
                recovered.values["incident_id"]
                == task["incident_id"]
            )

            print(
                "[PASS] 重新打开 SQLite 后恢复审批状态"
            )

            # ------------------------------------------------
            # 6.4 使用真实审批服务
            # ------------------------------------------------

            service = load_service(graph2)

            ticket_module = importlib.import_module(
                "app.tools.ticket_tool"
            )

            with patch.object(
                ticket_module,
                "DB_PATH",
                maintenance_db,
            ):

                result = service.resume_agent_approval(
                    task_id=task["task_id"],
                    approved=True,
                    task_store=task_store,
                )

                assert result["resumed"] is True
                assert result["status"] == "completed"
                assert result["ticket_created"] is True
                assert result["ticket_status"] == "created"
                assert result["ticket_id"]

                print(
                    "[PASS] 重连后审批通过并创建正式工单"
                )

                # --------------------------------------------
                # 6.5 验证 TaskStore
                # --------------------------------------------

                saved_task = task_store.get_task(
                    task["task_id"]
                )

                assert saved_task["status"] == "completed"

                print(
                    "[PASS] 恢复后的 TaskStore 状态正确"
                )

                # --------------------------------------------
                # 6.6 验证 Checkpoint
                # --------------------------------------------

                after = graph2.get_state(config)

                assert not after.next

                assert (
                    after.values["ticket_approved"] is True
                )

                assert (
                    after.values["ticket_created"] is True
                )

                assert (
                    after.values["ticket_id"]
                    == result["ticket_id"]
                )

                print(
                    "[PASS] 恢复后的 Checkpoint 状态正确"
                )

                # --------------------------------------------
                # 6.7 验证工单幂等
                # --------------------------------------------

                assert count_tickets(maintenance_db) == 1

                repeated = service.resume_agent_approval(
                    task_id=task["task_id"],
                    approved=True,
                    task_store=task_store,
                )

                assert repeated["resumed"] is False
                assert count_tickets(maintenance_db) == 1

                print(
                    "[PASS] 恢复后重复审批没有生成第二张工单"
                )

            # ------------------------------------------------
            # 6.8 SQLite 数据完整性
            # ------------------------------------------------

            for db_path in (
                task_db,
                checkpoint_db,
                maintenance_db,
            ):

                check_integrity(db_path)

            print(
                "[PASS] 三个临时 SQLite 数据库完整性正常"
            )

        finally:

            connection2.close()

    print(
        "\nCheckpoint 重启恢复回归全部通过！"
    )
    print(
        "临时 SQLite 数据库已清理。"
    )


if __name__ == "__main__":
    main()
