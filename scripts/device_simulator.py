
"""
工业设备故障模拟器。

支持：
- 原有温度场景：normal / warning / critical / recovery
- E-101：编码器通信异常
- E-102：伺服驱动异常
- E-103：电机过温报警

模拟器负责生成数据；
Monitoring Engine 负责识别故障；
TaskStore 负责保存待执行的 Agent 任务。

当前为单轮模拟，持续运行模式后续增加。
"""

import argparse
import time

from datetime import datetime, timezone

from app.monitoring.device_config import load_device_config
from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore
from app.monitoring.monitoring_engine import MonitoringEngine

from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore

from app.tasks.monitoring_task_adapter import (
    enqueue_monitoring_events,
)


# ============================================================
# 1. 模拟场景
# ============================================================

SCENARIOS = {
    # 保留原来的温度测试场景
    "normal": [52.0, 53.2, 54.1, 53.5, 52.8],

    "warning": [54.0, 61.0, 66.5, 69.0, 70.0],

    "critical": [
        55.0, 64.0, 68.0, 73.0,
        77.0, 81.5, 82.0,
    ],

    "recovery": [
        81.5, 79.0, 74.0, 69.0,
        63.0, 57.0,
    ],

    # 新增三种故障场景
    "e101": [53.0, 53.1, 53.0, 53.2, 53.1],

    "e102": [54.0, 54.2, 54.1, 54.3, 54.0],

    "e103": [
        55.0, 64.0, 68.0, 73.0,
        77.0, 81.5, 82.0,
    ],
}

ROBOT_DEVICES = {"RB-001", "RB-002", "RB-003"}


# ============================================================
# 2. 根据场景创建采样
# ============================================================

def build_snapshot(
    device_id: str,
    temperature: float,
    temperature_limit: float,
    scenario: str = "normal",
    sample_index: int = 1,
) -> DeviceSnapshot:
    """
    sample_index 从 1 开始。

    E-101：
        第1次正常；
        第2次开始通信失败；
        连续错误达到3次时触发。

    E-102：
        第1次正常；
        第2次开始驱动器报告故障。

    E-103：
        温度超过安全限值时，
        模拟机器人控制器报告 E-103。
    """

    encoder_comm_ok = True
    encoder_error_count = 0

    servo_drive_status = "normal"
    drive_alarm_subcode = None

    current_alarm = None

    # --------------------------------------------
    # E-101：模拟编码器连续通信失败
    # --------------------------------------------
    if scenario == "e101" and sample_index >= 2:
        encoder_comm_ok = False
        encoder_error_count = sample_index - 1

        if encoder_error_count >= 3:
            current_alarm = "E-101"

    # --------------------------------------------
    # E-102：模拟伺服驱动器报告过流
    # --------------------------------------------
    elif scenario == "e102" and sample_index >= 2:
        servo_drive_status = "fault"
        drive_alarm_subcode = "OVERCURRENT"
        current_alarm = "E-102"

    # --------------------------------------------
    # E-103：模拟控制器报告电机过温
    # --------------------------------------------
    elif (
        scenario in ("e103", "critical")
        and device_id in ROBOT_DEVICES
        and temperature > temperature_limit
    ):
        current_alarm = "E-103"

    return DeviceSnapshot(
        device_id=device_id,
        temperature=temperature,
        current_alarm=current_alarm,
        running_status="running",
        sampled_at=datetime.now(timezone.utc),
        source="device_simulator",
        encoder_comm_ok=encoder_comm_ok,
        encoder_error_count=encoder_error_count,
        servo_drive_status=servo_drive_status,
        drive_alarm_subcode=drive_alarm_subcode,
    )


# ============================================================
# 3. 运行单轮模拟
# ============================================================

def run_simulator(
    device_id: str,
    scenario: str,
    interval: float = 2.0,
    state_store: DeviceStateStore | None = None,
    incident_store: IncidentStore | None = None,
    task_store: TaskStore | None = None,
) -> list[dict]:

    if scenario not in SCENARIOS:
        raise ValueError(
            f"不支持的模拟场景：{scenario}"
        )

    if interval < 0:
        raise ValueError("interval 不能小于 0")

    device_id = device_id.strip().upper()

    # 手册仅适用于 RB 系列机器人。
    if (
        scenario in ("e101", "e102", "e103")
        and device_id not in ROBOT_DEVICES
    ):
        raise ValueError(
            f"{device_id} 不支持 {scenario} 故障场景"
        )

    config = load_device_config(device_id)

    warning = config["temperature_warning"]
    limit = config["temperature_limit"]

    if state_store is None:
        state_store = DeviceStateStore()

    if incident_store is None:
        incident_store = IncidentStore()

    if task_store is None:
        task_store = TaskStore()

    engine = MonitoringEngine(
        state_store=state_store,
        incident_store=incident_store,
    )

    temperatures = SCENARIOS[scenario]
    results = []

    print(f"设备：{device_id}")
    print(f"名称：{config['device_name']}")
    print(f"场景：{scenario}")
    print(f"Warning 阈值：{warning}℃")
    print(f"Critical 限值：{limit}℃")
    print("-" * 60)

    for index, temperature in enumerate(
        temperatures,
        start=1,
    ):
        # 1. 模拟设备产生一条采样
        snapshot = build_snapshot(
            device_id=device_id,
            temperature=temperature,
            temperature_limit=limit,
            scenario=scenario,
            sample_index=index,
        )

        # 2. 监控引擎识别故障并登记 Incident
        monitoring_result = engine.process_snapshot(
            snapshot=snapshot,
            warning=warning,
            limit=limit,
        )

        # 3. 遍历故障事件，登记真实 Agent Task
        task_results = enqueue_monitoring_events(
            monitoring_result=monitoring_result,
            task_store=task_store,
        )

        events = monitoring_result["events"]

        # 4. 保留原接口需要的顶层字段
        #    若存在多个事件，顶层展示第一个事件；
        #    完整故障列表仍以 events 为准。
        representative_event = next(
            (
                event
                for event in events
                if event["should_trigger"]
            ),
            events[0] if events else None,
        )

        created_tasks = [
            item["task"]
            for item in task_results
            if item["task"] is not None
            and item["task"]["created"]
        ]

        registered_tasks = [
            item["task"]
            for item in task_results
            if item["task"] is not None
        ]

        result = {
            **monitoring_result,

            "risk_level": (
                representative_event["risk_level"]
                if representative_event
                else monitoring_result["risk_level"]
            ),

            "incident_id": (
                representative_event["incident_id"]
                if representative_event
                else None
            ),

            "should_trigger": any(
                event["should_trigger"]
                for event in events
            ),

            "task_enqueued": bool(registered_tasks),

            "task_id": (
                registered_tasks[0]["task_id"]
                if registered_tasks
                else None
            ),

            "task_created": bool(created_tasks),

            # 新增：保留每个故障对应的任务结果
            "task_results": task_results,
        }

        results.append(result)

        alarm = snapshot.current_alarm or "-"
        fault_codes = [
            event["alarm_code"] or "过温无明确报警"
            for event in events
        ]

        print(
            f"[{index}/{len(temperatures)}] "
            f"温度={temperature:.1f}℃ | "
            f"报警={alarm} | "
            f"故障={fault_codes or '无'} | "
            f"新增任务={len(created_tasks)}"
        )

        if scenario == "e101":
            print(
                f"  编码器通信={snapshot.encoder_comm_ok} | "
                f"连续失败={snapshot.encoder_error_count}"
            )

        elif scenario == "e102":
            print(
                f"  驱动器状态={snapshot.servo_drive_status} | "
                f"子码={snapshot.drive_alarm_subcode}"
            )

        for task in created_tasks:
            print(
                f"  → 已创建 Agent Task：{task['task_id']}"
            )

        if index < len(temperatures):
            time.sleep(interval)

    print("-" * 60)
    print("本轮模拟和任务登记结束。")

    return results


# ============================================================
# 4. 命令行入口
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="工业设备多故障模拟器"
    )

    parser.add_argument(
        "--device",
        default="RB-001",
        help="设备编号",
    )

    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="critical",
        help="模拟场景",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="相邻采样间隔（秒）",
    )

    args = parser.parse_args()

    run_simulator(
        device_id=args.device,
        scenario=args.scenario,
        interval=args.interval,
    )


if __name__ == "__main__":
    main()
