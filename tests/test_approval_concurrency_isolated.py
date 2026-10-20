
"""
人工审批并发竞态检测。

目的：
检查两个审批请求同时进入 approval_service 时，
是否可能重复调用 LangGraph 的 graph.invoke()。

使用真实：
- resume_agent_approval
- TaskStore

使用模拟：
- LangGraph Graph

安全：
- TaskStore 使用临时 SQLite
- 不加载正式 Agent Graph
- 不创建任何真实维修工单
- 不调用 LLM/RAG

注意：
这是服务层竞态检测，不是真实 Checkpointer 并发测试。
发现重复调用时应报告 FAIL，而不是隐藏问题。
"""

import importlib
import sys
import types

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, BrokenBarrierError, Lock
from types import SimpleNamespace
from unittest.mock import patch

from app.tasks.task_store import TaskStore


# ============================================================
# 1. 受控模拟 Graph
# ============================================================

class ControlledGraph:
    """
    模拟等待审批的 LangGraph。

    barrier 用于让两个请求同时到达 invoke，
    从而确定性地暴露审批服务的竞态窗口。

    不执行真实工单创建。
    """

    def __init__(self, task, barrier=None):
        self.task = task
        self.barrier = barrier
        self._lock = Lock()
        self.invocations = 0
        self.finished = False

    def get_state(self, config):

        assert (
            config["configurable"]["thread_id"]
            == self.task["thread_id"]
        )

        with self._lock:
            finished = self.finished

        if finished:
            return SimpleNamespace(
                tasks=(),
                next=(),
                values={
                    "task_id": self.task["task_id"],
                    "incident_id": self.task["incident_id"],
                    "ticket_status": "created",
                    "ticket_approved": True,
                    "ticket_created": True,
                    "ticket_id": "WO-SIMULATED-NOT-PERSISTED",
                },
            )

        return SimpleNamespace(
            tasks=(
                SimpleNamespace(
                    name="approval",
                    interrupts=("pending",),
                ),
            ),
            next=("approval",),
            values={
                "task_id": self.task["task_id"],
                "incident_id": self.task["incident_id"],
                "ticket_status": "pending_approval",
            },
        )

    def invoke(self, command, config):

        with self._lock:
            self.invocations += 1

        # 尽量让两个审批请求同时到达这里
        if self.barrier is not None:
            try:
                self.barrier.wait(timeout=8)
            except BrokenBarrierError:
                pass

        with self._lock:
            self.finished = True

        return {}


# ============================================================
# 2. 安全加载真实审批服务
# ============================================================

def load_real_service():
    """
    避免导入正式 app.agent.graph，
    防止触发正式 Checkpoint 初始化。
    """

    if "app.agent.graph" in sys.modules:
        raise RuntimeError(
            "正式 Agent Graph 已加载，为安全起见停止"
        )

    fake_module = types.ModuleType(
        "app.agent.graph"
    )

    fake_module.graph = object()

    with patch.dict(
        sys.modules,
        {"app.agent.graph": fake_module},
    ):
        service = importlib.import_module(
            "app.tasks.approval_service"
        )

    return service


# ============================================================
# 3. 创建等待审批的任务
# ============================================================

def make_waiting_task(store, incident_id):

    task = store.enqueue_task(
        incident_id=incident_id,
        device_id="RB-001",
        risk_level="fault",
    )

    assert store.claim_task(
        task["task_id"]
    )

    assert store.transition_task(
        task_id=task["task_id"],
        expected_status="running",
        new_status="waiting_approval",
    )

    return task


# ============================================================
# 4. 执行单个审批请求
# ============================================================

def call_approval(service, store, task):

    try:
        result = service.resume_agent_approval(
            task_id=task["task_id"],
            approved=True,
            task_store=store,
        )

        return ("ok", result)

    except Exception as exc:
        return (
            "error",
            f"{type(exc).__name__}: {exc}",
        )


# ============================================================
# 5. 主测试
# ============================================================

def main():

    service = load_real_service()

    with TemporaryDirectory(
        prefix="approval_concurrency_"
    ) as directory:

        store = TaskStore(
            db_path=Path(directory) / "tasks.db"
        )

        # ----------------------------------------------------
        # 5.1 对照组：顺序重复审批
        # ----------------------------------------------------

        sequential_task = make_waiting_task(
            store,
            "INC-CONC-SEQ",
        )

        sequential_graph = ControlledGraph(
            sequential_task
        )

        with patch.object(
            service,
            "graph",
            sequential_graph,
        ):

            first = call_approval(
                service,
                store,
                sequential_task,
            )

            repeated = call_approval(
                service,
                store,
                sequential_task,
            )

        assert (
            first[0] == "ok"
            and first[1]["resumed"] is True
        )

        assert (
            repeated[0] == "ok"
            and repeated[1]["resumed"] is False
        )

        assert sequential_graph.invocations == 1

        print(
            "[PASS] 顺序重复审批只恢复一次 Graph"
        )

        # ----------------------------------------------------
        # 5.2 并发组：两个请求同时审批
        # ----------------------------------------------------

        concurrent_task = make_waiting_task(
            store,
            "INC-CONC-PAR",
        )

        concurrent_graph = ControlledGraph(
            concurrent_task,
            barrier=Barrier(2),
        )

        with patch.object(
            service,
            "graph",
            concurrent_graph,
        ):

            with ThreadPoolExecutor(
                max_workers=2
            ) as executor:

                futures = [
                    executor.submit(
                        call_approval,
                        service,
                        store,
                        concurrent_task,
                    )
                    for _ in range(2)
                ]

                outcomes = [
                    future.result(timeout=15)
                    for future in futures
                ]

        # ----------------------------------------------------
        # 5.3 统计结果
        # ----------------------------------------------------

        success_count = sum(
            status == "ok"
            and detail.get("resumed") is True
            for status, detail in outcomes
            if status == "ok"
        )

        final_status = store.get_task(
            concurrent_task["task_id"]
        )["status"]

        print("\n===== 并发审批检测结果 =====")

        print(
            f"并发请求结果：{outcomes}"
        )

        print(
            f"Graph.invoke 次数："
            f"{concurrent_graph.invocations}"
        )

        print(
            f"TaskStore 最终状态：{final_status}"
        )

        print(
            f"成功完成审批的请求数：{success_count}"
        )

        # ----------------------------------------------------
        # 5.4 检测审批重复执行风险
        # ----------------------------------------------------

        if concurrent_graph.invocations > 1:

            print(
                "\n[FAIL] 并发审批互斥未通过："
                "Graph 被重复恢复"
            )

            print(
                "注意：测试使用模拟 Graph，"
                "没有创建任何真实维修工单。"
            )

            return 1

        if (
            concurrent_graph.invocations == 1
            and final_status == "completed"
            and success_count == 1
        ):

            print(
                "\n[PASS] 此次受控测试未发现"
                "重复 Graph 恢复"
            )

            return 0

        print(
            "\n[REVIEW] 并发结果不明确，"
            "需要进一步检查"
        )

        return 2


# ============================================================
# 6. 程序入口
# ============================================================

if __name__ == "__main__":
    raise SystemExit(main())
