"""TaskStore 回归测试：仅使用临时数据库，不读写项目 data/ 目录。

在项目根目录执行：
    python scripts/test_task_store_regression.py
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from app.tasks.task_store import TaskStore


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with TemporaryDirectory(prefix="task_store_test_") as tmp:
        store = TaskStore(db_path=Path(tmp) / "agent_tasks_test.db")

        # 1. 同一 Incident + 风险等级只允许一条任务。
        first = store.enqueue_task("INC-TEST-001", "rb-001", "fault")
        duplicate = store.enqueue_task("INC-TEST-001", "RB-001", "FAULT")
        check(first["created"] is True, "首个任务应该创建成功")
        check(duplicate["created"] is False, "重复任务应该复用旧记录")
        check(first["task_id"] == duplicate["task_id"], "去重后 task_id 不应改变")
        check(first["device_id"] == "RB-001", "设备 ID 应归一化为大写")
        print("[PASS] 同类任务去重及输入规范化")

        # 2. 同一 Incident 的 warning 与 critical 是两个不同处置任务。
        warn = store.enqueue_task("INC-TEST-TEMP", "RB-003", "warning")
        critical = store.enqueue_task("INC-TEST-TEMP", "RB-003", "critical")
        check(warn["task_id"] != critical["task_id"], "不同风险等级应可建立独立任务")
        check(len(store.get_tasks_by_incident("INC-TEST-TEMP")) == 2, "应有两条任务")
        print("[PASS] 同一 Incident 不同风险等级的任务区分")

        # 3. 并发入队：所有请求应复用同一个 task_id。
        def concurrent_enqueue(_: int) -> dict:
            return store.enqueue_task("INC-TEST-RACE", "RB-002", "fault")

        with ThreadPoolExecutor(max_workers=6) as executor:
            enqueued = list(executor.map(concurrent_enqueue, range(12)))
        check(len({item["task_id"] for item in enqueued}) == 1, "并发入队未正确去重")
        check(sum(bool(item["created"]) for item in enqueued) == 1, "并发入队应恰好创建一次")
        print("[PASS] 并发入队去重（12 次请求）")

        # 4. 并发领取：同一 Pending 任务只能有一位领取者。
        with ThreadPoolExecutor(max_workers=6) as executor:
            claimed = list(executor.map(store.claim_task, [first["task_id"]] * 12))
        check(sum(claimed) == 1, "同一任务被多次领取")
        current = store.get_task(first["task_id"])
        check(current is not None and current["status"] == "running", "领取后应为 running")
        check(current["attempt_count"] == 1, "成功领取次数应为 1")
        print("[PASS] 并发原子领取（12 次请求）")

        # 5. 审批等待状态与终态：拒绝非法/过期状态转换。
        task_id = first["task_id"]
        check(store.transition_task(task_id, "running", "waiting_approval"), "进入审批等待失败")
        check(not store.transition_task(task_id, "running", "completed"), "旧状态 CAS 应返回 False")
        check(store.transition_task(task_id, "waiting_approval", "completed"), "任务完成失败")
        check(not store.claim_task(task_id), "已完成任务不能再次领取")
        check(not store.transition_task(task_id, "waiting_approval", "completed"), "已完成任务不应再次完成")
        print("[PASS] 审批等待、原子状态迁移及终态保护")

        # 6. 失败恢复：只有 failed 才能重新进入 pending。
        retry = store.enqueue_task("INC-TEST-RETRY", "RB-002", "fault")
        retry_id = retry["task_id"]
        check(store.claim_task(retry_id), "首次领取失败")
        check(store.transition_task(retry_id, "running", "failed", "test failure"), "failed 迁移失败")
        check(store.transition_task(retry_id, "failed", "pending"), "failed->pending 重试失败")
        check(store.claim_task(retry_id), "重试领取失败")
        check(store.get_task(retry_id)["attempt_count"] == 2, "重试后次数应该等于 2")
        print("[PASS] failed -> pending 重试及 attempt_count")

        # 7. 查询过滤和输入验证。
        check(any(t["task_id"] == warn["task_id"] for t in store.list_tasks(status="pending")), "Pending 过滤异常")
        check(all(t["device_id"] == "RB-003" for t in store.list_tasks(device_id="rb-003")), "设备过滤异常")
        check(all(t["status"] == "pending" for t in store.list_pending_tasks()), "待处理查询应仅返回 pending")
        try:
            store.enqueue_task("INC-INVALID", "RB-001", "unknown")
        except ValueError:
            pass
        else:
            raise AssertionError("非法风险等级未被拒绝")
        print("[PASS] 查询过滤及非法风险等级校验")

    print("\n全部 7 组 TaskStore 回归测试通过。未修改项目正式 SQLite 数据库。")


if __name__ == "__main__":
    main()
