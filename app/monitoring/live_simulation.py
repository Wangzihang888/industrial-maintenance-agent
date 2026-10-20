
"""
持续运行设备模拟器。

职责：
1. 每台设备独立持续采样
2. 支持正常、E-101、E-102、E-103、恢复场景
3. 调用 Monitoring Engine 检测异常
4. 登记新 Agent Task
5. 故障连续恢复 3 次后关闭对应 Incident
6. Agent 任务在独立线程执行，不阻塞采样

范围：本机单进程演示。
"""

from queue import Queue
from threading import Event, Lock, Thread

from datetime import datetime, timezone

from app.monitoring.device_config import load_device_config
from app.monitoring.device_state_models import DeviceSnapshot
from app.monitoring.device_state_store import DeviceStateStore
from app.monitoring.monitoring_engine import MonitoringEngine

from app.incidents.incident_store import IncidentStore
from app.tasks.task_store import TaskStore
from app.tasks.monitoring_task_adapter import enqueue_monitoring_events


SCENARIOS = {
    "normal",
    "e101",
    "e102",
    "e103",
    "recovery",
}

ROBOT_DEVICES = {"RB-001", "RB-002", "RB-003"}

INCIDENT_KEYS = (
    "encoder:communication",
    "servo:drive_fault",
    "temperature:overheat",
)

RECOVERY_SAMPLES = 3


class LiveSimulationManager:
    """
    管理当前 FastAPI 进程中的持续模拟。

    每台设备最多有一个采样线程。
    Agent 使用独立的任务队列执行。
    """

    def __init__(self):
        self.sessions = {}
        self.lock = Lock()

        self.agent_queue = Queue()
        self.agent_results = {}

        self.agent_thread = Thread(
            target=self._agent_worker,
            daemon=True,
        )
        self.agent_thread.start()

    # ========================================================
    # 1. 校验设备与场景
    # ========================================================

    def _validate(self, device_id, scenario):
        device_id = device_id.strip().upper()
        scenario = scenario.strip().lower()

        config = load_device_config(device_id)

        if scenario not in SCENARIOS:
            raise ValueError("不支持的模拟场景")

        if (
            scenario in ("e101", "e102", "e103")
            and device_id not in ROBOT_DEVICES
        ):
            raise ValueError(
                "当前设备不支持该机器人故障场景"
            )

        return device_id, scenario, config

    # ========================================================
    # 2. 启动某台设备
    # ========================================================

    def start(self, device_id, scenario="normal", interval=2.0):
        device_id, scenario, config = self._validate(
            device_id, scenario
        )

        if not 0.5 <= interval <= 10:
            raise ValueError("采样间隔必须在 0.5～10 秒")

        with self.lock:
            existing = self.sessions.get(device_id)

            if (existing
                and existing["status"]  in ("running", "stopping")):
                raise ValueError("该设备已经在运行")

            session = {
                "device_id": device_id,
                "device_name": config["device_name"],
                "scenario": scenario,
                "interval": interval,
                "status": "running",
                "sample_count": 0,
                "temperature": 53.0,
                "encoder_error_count": 0,
                "recovery_counts": {
                    key: 0 for key in INCIDENT_KEYS
                },
                "last_events": [],
                "created_task_ids": [],
                "error": None,
                "stop_event": Event(),
            }

            self.sessions[device_id] = session

            thread = Thread(
                target=self._run_device,
                args=(session, config),
                daemon=True,
            )

            session["thread"] = thread
            thread.start()

        return self.get_device(device_id)

    # ========================================================
    # 3. 切换运行场景
    # ========================================================

    def set_scenario(self, device_id, scenario):
        device_id, scenario, _ = self._validate(
            device_id, scenario
        )

        with self.lock:
            session = self.sessions.get(device_id)

            if not session or session["status"] != "running":
                raise ValueError("该设备未运行")

            session["scenario"] = scenario

        return self.get_device(device_id)

    # ========================================================
    # 4. 停止设备模拟
    # ========================================================

    def stop(self, device_id):
        device_id = device_id.strip().upper()

        with self.lock:
            session = self.sessions.get(device_id)

            if not session or session["status"] != "running":
                raise ValueError("该设备未运行")

            session["stop_event"].set()
            session["status"] = "stopping"

        return self.get_device(device_id)

    # ========================================================
    # 5. 生成一个设备采样
    # ========================================================

    def _build_snapshot(self, session, config):
        scenario = session["scenario"]
        temperature = session["temperature"]

        warning = config["temperature_warning"]
        limit = config["temperature_limit"]

        # 默认所有通信和驱动信号正常
        encoder_comm_ok = True
        servo_status = "normal"
        drive_subcode = None
        alarm_code = None

        if scenario == "e101":
            # 连续模拟通信失败
            session["encoder_error_count"] += 1
            encoder_comm_ok = False

            if session["encoder_error_count"] >= 3:
                alarm_code = "E-101"

            temperature = 53.0

        elif scenario == "e102":
            session["encoder_error_count"] = 0
            servo_status = "fault"
            drive_subcode = "OVERCURRENT"
            alarm_code = "E-102"
            temperature = 54.0

        elif scenario == "e103":
            session["encoder_error_count"] = 0

            # 逐步升温，最高控制在限值以上约 7℃
            temperature = min(
                temperature + 4.5,
                limit + 7.0,
            )

            if temperature > limit:
                alarm_code = "E-103"

        else:
            # normal / recovery 都模拟正常信号
            session["encoder_error_count"] = 0

            # 温度逐步下降，不瞬间跳回基线
            temperature = max(
                53.0,
                temperature - 5.0,
            )

        session["temperature"] = temperature

        return DeviceSnapshot(
            device_id=session["device_id"],
            temperature=temperature,
            current_alarm=alarm_code,
            running_status="running",
            sampled_at=datetime.now(timezone.utc),
            source="device_simulator",
            encoder_comm_ok=encoder_comm_ok,
            encoder_error_count=session["encoder_error_count"],
            servo_drive_status=servo_status,
            drive_alarm_subcode=drive_subcode,
        )

    # ========================================================
    # 6. 恢复处理
    # ========================================================

    def _check_recovery(
        self,
        session,
        active_keys,
        incident_store,
    ):
        """
        同一故障连续 3 次未检出，
        才关闭其活动 Incident。

        不修改任何正式维修工单。
        """

        device_id = session["device_id"]

        for incident_key in INCIDENT_KEYS:
            if incident_key in active_keys:
                session["recovery_counts"][incident_key] = 0
                continue

            session["recovery_counts"][incident_key] += 1

            if (
                session["recovery_counts"][incident_key]
                < RECOVERY_SAMPLES
            ):
                continue

            incident = incident_store.get_active_incident(
                device_id=device_id,
                incident_key=incident_key,
            )

            if incident is not None:
                incident_store.close_incident(
                    incident["incident_id"]
                )

    # ========================================================
    # 7. 持续采样线程
    # ========================================================

    def _run_device(self, session, config):
        device_id = session["device_id"]

        try:
            state_store = DeviceStateStore()
            incident_store = IncidentStore()
            task_store = TaskStore()

            engine = MonitoringEngine(
                state_store=state_store,
                incident_store=incident_store,
            )

            while not session["stop_event"].is_set():
                with self.lock:
                    snapshot = self._build_snapshot(
                        session, config
                    )

                monitoring_result = engine.process_snapshot(
                    snapshot=snapshot,
                    warning=config["temperature_warning"],
                    limit=config["temperature_limit"],
                )

                task_results = enqueue_monitoring_events(
                    monitoring_result=monitoring_result,
                    task_store=task_store,
                )

                active_keys = {
                    event["incident_key"]
                    for event in monitoring_result["events"]
                }

                self._check_recovery(
                    session=session,
                    active_keys=active_keys,
                    incident_store=incident_store,
                )

                created_ids = []

                for item in task_results:
                    task = item["task"]

                    if task and task["created"]:
                        created_ids.append(task["task_id"])

                        # 只调度本次新建的 Task，
                        # 避免意外执行历史 pending 任务。
                        self.agent_queue.put(task["task_id"])

                with self.lock:
                    session["sample_count"] += 1
                    session["last_events"] = monitoring_result["events"]
                    session["created_task_ids"].extend(created_ids)

                # Event.wait 能在停止时立即唤醒
                session["stop_event"].wait(
                    session["interval"]
                )

        except Exception as exc:
            with self.lock:
                session["status"] = "failed"
                session["error"] = str(exc)

        finally:
            with self.lock:
                if session["status"] != "failed":
                    session["status"] = "stopped"

    # ========================================================
    # 8. 独立 Agent 执行线程
    # ========================================================

    def _agent_worker(self):
        """
        与采样线程分离。

        当前 MVP 使用一个 Agent 工作线程，
        避免同时执行过多大模型请求。
        """

        from app.tasks.agent_runner import run_agent_task

        while True:
            task_id = self.agent_queue.get()

            try:
                with self.lock:
                    self.agent_results[task_id] = {
                        "status": "running",
                    }

                result = run_agent_task(task_id)

                with self.lock:
                    self.agent_results[task_id] = {
                        "status": result["status"],
                    }

            except Exception as exc:
                with self.lock:
                    self.agent_results[task_id] = {
                        "status": "failed",
                        "error": str(exc),
                    }

            finally:
                self.agent_queue.task_done()

    # ========================================================
    # 9. 查询状态
    # ========================================================

    def get_device(self, device_id):
        device_id = device_id.strip().upper()

        with self.lock:
            session = self.sessions.get(device_id)

            if session is None:
                return None

            # 不暴露 Thread / Event 对象给 FastAPI
            return {
                "device_id": device_id,
                "device_name": session["device_name"],
                "scenario": session["scenario"],
                "status": session["status"],
                "sample_count": session["sample_count"],
                "temperature": session["temperature"],
                "encoder_error_count": session["encoder_error_count"],
                "last_events": list(session["last_events"]),
                "created_task_ids": list(
                    session["created_task_ids"]
                ),
                "error": session["error"],
            }

    def list_devices(self):
        with self.lock:
            device_ids = list(self.sessions)

        return [
            self.get_device(device_id)
            for device_id in device_ids
        ]

    def list_agent_results(self):
        with self.lock:
            return {
                key: value.copy()
                for key, value in self.agent_results.items()
            }


# 单进程内共享一个管理器
live_simulation_manager = LiveSimulationManager()
