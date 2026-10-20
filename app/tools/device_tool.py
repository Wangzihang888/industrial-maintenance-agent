
import json

from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.monitoring.device_state_store import (
    DeviceStateStore,
)


# ============================================================
# 1. 设备静态配置文件
# ============================================================

DATA_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "devices.json"
)


# ============================================================
# 2. 查询设备当前状态
# ============================================================

@tool
def get_device_status(device_id: str) -> dict[str, Any]:
    """
    根据设备 ID 查询当前状态。

    静态配置：
        data/devices.json

    动态运行状态：
        data/device_state.db

    保留原有 result_type 和 device 返回结构，
    兼容现有 LangGraph Extract Node。
    """

    # --------------------------------------------------------
    # 3. 标准化设备编号
    # --------------------------------------------------------

    device_id = device_id.strip().upper()

    if not device_id:
        return {
            "success": False,
            "device_id": device_id,
            "result_type": "device_status",
            "error": "invalid_device_id",
        }

    # --------------------------------------------------------
    # 4. 读取设备静态配置
    # --------------------------------------------------------

    with DATA_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        devices = json.load(file)

    device_config = devices.get(device_id)

    if device_config is None:
        return {
            "success": False,
            "device_id": device_id,
            "result_type": "device_status",
            "error": "device_not_found",
        }

    # --------------------------------------------------------
    # 5. 查询 SQLite 最新运行状态
    # --------------------------------------------------------

    state_store = DeviceStateStore()

    latest_state = state_store.get_latest_state(
        device_id=device_id
    )

    if latest_state is None:
        return {
            "success": False,
            "device_id": device_id,
            "result_type": "device_status",
            "error": "device_state_unavailable",
        }

    # --------------------------------------------------------
    # 6. 合并静态配置与动态状态
    # --------------------------------------------------------

    device = {
        "device_id": device_config["device_id"],
        "device_name": device_config["device_name"],
        "device_type": device_config["device_type"],

        "temperature_warning": (
            device_config["temperature_warning"]
        ),

        "temperature_limit": (
            device_config["temperature_limit"]
        ),

        # 以下字段以 SQLite 最新数据为准。
        "temperature": latest_state["temperature"],

        # 保持旧版设备对象的 status 字段名称，
        # 兼容现有业务代码。
        "status": latest_state["running_status"],

        "current_alarm": latest_state["current_alarm"],

        # 新增：数据采样时间及来源。
        "sampled_at": latest_state["sampled_at"],
        "source": latest_state["source"],
    }

    # --------------------------------------------------------
    # 7. 保留原有 Tool 输出契约
    # --------------------------------------------------------

    return {
        "success": True,
        "result_type": "device_status",
        "device": device,
    }
