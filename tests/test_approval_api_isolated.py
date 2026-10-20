
"""
审批 HTTP API 隔离回归测试。

验证：
1. 任务不存在 -> 404
2. Warning 任务禁止审批 -> 409
3. 已完成任务重复审批 -> 200，不重复恢复
4. 非等待审批任务 -> 409
5. 不合法的请求参数 -> 422
6. Fault 任务审批通过 -> 200
7. Critical 任务审批拒绝 -> 200
8. 审批服务抛出业务异常 -> 409

隔离原则：
- 使用真实 FastAPI 审批路由与 Pydantic Schema
- Mock TaskStore
- Mock resume_agent_approval
- 不导入真实 Agent Graph
- 不访问正式 SQLite 数据库
- 不创建维修工单
- 不调用 LLM/RAG

注意：
本测试验证 HTTP 接口层，不代替此前已经完成的
真实审批服务和工单数据库集成测试。
"""

import importlib
import sys
import types

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ============================================================
# 1. 安全导入审批路由
# ============================================================

def load_approval_router():

    if "app.api.approval_router" in sys.modules:
        raise RuntimeError(
            "审批路由已提前加载，请在独立进程运行测试"
        )

    # 避免路由导入真实审批服务，
    # 从而避免加载默认 LangGraph Checkpoint。
    fake_service = types.ModuleType(
        "app.tasks.approval_service"
    )

    fake_service.resume_agent_approval = Mock()

    with patch.dict(
        sys.modules,
        {
            "app.tasks.approval_service": fake_service,
        },
    ):
        module = importlib.import_module(
            "app.api.approval_router"
        )

    if "app.agent.graph" in sys.modules:
        raise RuntimeError(
            "测试期间意外加载了真实 Agent Graph"
        )

    return module


# ============================================================
# 2. 模拟 TaskStore
# ============================================================

class FakeTaskStore:

    def __init__(self):

        self.tasks = {
            "TASK-FAULT": {
                "task_id": "TASK-FAULT",
                "risk_level": "fault",
                "status": "waiting_approval",
            },
            "TASK-CRITICAL": {
                "task_id": "TASK-CRITICAL",
                "risk_level": "critical",
                "status": "waiting_approval",
            },
            "TASK-WARNING": {
                "task_id": "TASK-WARNING",
                "risk_level": "warning",
                "status": "pending",
            },
            "TASK-COMPLETED": {
                "task_id": "TASK-COMPLETED",
                "risk_level": "fault",
                "status": "completed",
            },
            "TASK-PENDING": {
                "task_id": "TASK-PENDING",
                "risk_level": "fault",
                "status": "pending",
            },
            "TASK-ERROR": {
                "task_id": "TASK-ERROR",
                "risk_level": "fault",
                "status": "waiting_approval",
            },
        }

    def get_task(self, task_id):

        return self.tasks.get(task_id)


# ============================================================
# 3. 模拟审批服务
# ============================================================

def fake_resume_agent_approval(
    task_id,
    approved,
    task_store,
):

    if task_id == "TASK-ERROR":
        raise RuntimeError(
            "模拟 Checkpoint 与 TaskStore 不一致"
        )

    return {
        "task_id": task_id,
        "approved": approved,
        "resumed": True,
        "status": "completed",
        "ticket_created": approved,
        "ticket_status": (
            "created" if approved else "rejected"
        ),
    }


# ============================================================
# 4. 主测试
# ============================================================

def main():

    router_module = load_approval_router()

    app = FastAPI()

    app.include_router(
        router_module.router
    )

    store = FakeTaskStore()

    resume_mock = Mock(
        side_effect=fake_resume_agent_approval
    )

    with (
        patch.object(
            router_module,
            "TaskStore",
            return_value=store,
        ),
        patch.object(
            router_module,
            "resume_agent_approval",
            resume_mock,
        ),
        TestClient(app) as client,
    ):

        # ----------------------------------------------------
        # 4.1 任务不存在
        # ----------------------------------------------------

        response = client.post(
            "/api/tasks/TASK-NOT-FOUND/approval",
            json={"approved": True},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "task_not_found"

        print("[PASS] 不存在的任务返回 HTTP 404")

        # ----------------------------------------------------
        # 4.2 Warning 禁止审批
        # ----------------------------------------------------

        response = client.post(
            "/api/tasks/TASK-WARNING/approval",
            json={"approved": True},
        )

        assert response.status_code == 409

        assert (
            response.json()["detail"]
            == "task_does_not_require_approval"
        )

        print("[PASS] Warning 任务禁止审批")

        # ----------------------------------------------------
        # 4.3 已完成任务重复审批
        # ----------------------------------------------------

        response = client.post(
            "/api/tasks/TASK-COMPLETED/approval",
            json={"approved": True},
        )

        assert response.status_code == 200

        assert response.json()["resumed"] is False

        assert (
            response.json()["reason"]
            == "task_already_completed"
        )

        assert resume_mock.call_count == 0

        print("[PASS] 已完成任务不重复调用审批服务")

        # ----------------------------------------------------
        # 4.4 Pending 状态禁止审批
        # ----------------------------------------------------

        response = client.post(
            "/api/tasks/TASK-PENDING/approval",
            json={"approved": True},
        )

        assert response.status_code == 409

        assert (
            response.json()["detail"]
            == "task_not_waiting_approval"
        )

        print("[PASS] Pending 任务禁止审批")

        # ----------------------------------------------------
        # 4.5 不合法的 approved 参数
        # ----------------------------------------------------

        response = client.post(
            "/api/tasks/TASK-FAULT/approval",
            json={"approved": "invalid_boolean"},
        )

        assert response.status_code == 422

        assert resume_mock.call_count == 0

        print("[PASS] 非法审批参数返回 HTTP 422")

        # ----------------------------------------------------
        # 4.6 Fault 审批通过
        # ----------------------------------------------------

        response = client.post(
            "/api/tasks/TASK-FAULT/approval",
            json={"approved": True},
        )

        assert response.status_code == 200

        data = response.json()

        assert data["approved"] is True
        assert data["resumed"] is True
        assert data["ticket_created"] is True
        assert data["ticket_status"] == "created"

        print("[PASS] Fault 审批请求正确转交服务层")

        # ----------------------------------------------------
        # 4.7 Critical 审批拒绝
        # ----------------------------------------------------

        response = client.post(
            "/api/tasks/TASK-CRITICAL/approval",
            json={"approved": False},
        )

        assert response.status_code == 200

        data = response.json()

        assert data["approved"] is False
        assert data["resumed"] is True
        assert data["ticket_created"] is False
        assert data["ticket_status"] == "rejected"

        print("[PASS] Critical 拒绝请求正确转交服务层")

        # ----------------------------------------------------
        # 4.8 服务层异常转换为 HTTP 409
        # ----------------------------------------------------

        response = client.post(
            "/api/tasks/TASK-ERROR/approval",
            json={"approved": True},
        )

        assert response.status_code == 409

        assert (
            "Checkpoint"
            in response.json()["detail"]
        )

        print("[PASS] 审批服务业务异常返回 HTTP 409")

        # ----------------------------------------------------
        # 4.9 检查服务调用次数
        # ----------------------------------------------------

        assert resume_mock.call_count == 3

        print("[PASS] 审批服务实际调用次数正确")

    print(
        "\n审批 HTTP API 隔离回归全部通过！"
    )

    print(
        "未连接项目正式业务数据库。"
    )


# ============================================================
# 5. 程序入口
# ============================================================

if __name__ == "__main__":
    main()
