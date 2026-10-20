
"""
Agent 自动任务调度器。

职责：
1. 查询 pending 任务
2. 调用已有 Agent Runner
3. 支持执行一轮或持续轮询
4. 不自动审批维修工单
5. 不自动重试 failed 任务
"""

import argparse
import time
from collections.abc import Callable

from app.tasks.task_store import TaskStore


def process_pending_tasks(
    task_store: TaskStore,
    runner: Callable,
    device_id: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    执行一轮 pending 任务扫描。

    runner 由调用方传入，便于测试时
    替换为不调用大模型的假执行器。
    """

    tasks = task_store.list_pending_tasks(
        limit=limit,
        device_id=device_id,
    )

    results = []

    for task in tasks:
        task_id = task["task_id"]

        print(
            f"[Scheduler] 发现任务 "
            f"{task_id} | "
            f"{task['device_id']} | "
            f"{task['risk_level']}"
        )

        try:
            result = runner(
                task_id=task_id,
                task_store=task_store,
            )

            results.append(result)

            print(
                f"[Scheduler] 执行结果："
                f"{result.get('status')}"
            )

        except Exception as exc:
            print(
                f"[Scheduler] 任务执行异常："
                f"{task_id} | {exc}"
            )

            results.append({
                "task_id": task_id,
                "started": False,
                "status": "error",
                "error": str(exc),
            })

    return results


def run_scheduler(
    task_store: TaskStore,
    runner: Callable,
    interval: float = 3.0,
    device_id: str | None = None,
    once: bool = False,
    limit: int = 10,
) -> None:
    """
    once=True：
        只扫描并执行一轮。

    once=False：
        持续轮询，直到用户停止程序。
    """

    if interval <= 0:
        raise ValueError(
            "轮询间隔必须大于 0"
        )

    print("[Scheduler] 调度器已启动")
    print(f"[Scheduler] 设备筛选：{device_id or '全部'}")

    try:
        while True:

            results = process_pending_tasks(
                task_store=task_store,
                runner=runner,
                device_id=device_id,
                limit=limit,
            )

            if not results:
                print("[Scheduler] 当前没有待执行任务")

            if once:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[Scheduler] 已收到停止指令")

    print("[Scheduler] 调度器已退出")


def main() -> None:

    parser = argparse.ArgumentParser(
        description="企业设备运维 Agent 任务调度器"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="只执行一轮任务扫描",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="轮询间隔，单位秒",
    )

    parser.add_argument(
        "--device",
        default=None,
        help="可选：只执行指定设备任务",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="每轮最多领取的任务数量",
    )

    args = parser.parse_args()

    # 延迟导入：
    # 只有真正运行调度器时才加载 LangGraph。
    from app.tasks.agent_runner import run_agent_task

    store = TaskStore()

    run_scheduler(
        task_store=store,
        runner=run_agent_task,
        interval=args.interval,
        device_id=args.device,
        once=args.once,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
