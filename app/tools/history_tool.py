
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from typing import Any

from langchain_core.tools import tool

from app.monitoring.device_state_store import (
    DeviceStateStore,
)


# ============================================================
# 1. 查询设备历史温度
# ============================================================

@tool
def query_temperature_history(
    device_id: str,
    hours: int = 24,
) -> dict[str, Any]:
    """
    查询指定设备最近若干小时的温度历史。

    数据来源：
        data/device_state.db
        temperature_history 表

    保持原有 Tool 输出格式：
        success
        result_type
        device_id
        hours
        record_count
        records
    """

    # --------------------------------------------------------
    # 2. 标准化设备编号
    # --------------------------------------------------------

    device_id = device_id.strip().upper()

    if not device_id:
        return {
            "success": False,
            "result_type": "temperature_history",
            "device_id": device_id,
            "hours": hours,
            "record_count": 0,
            "records": [],
            "error": "invalid_device_id",
        }

    # --------------------------------------------------------
    # 3. 检查查询时长
    # --------------------------------------------------------

    if hours <= 0:
        return {
            "success": False,
            "result_type": "temperature_history",
            "device_id": device_id,
            "hours": hours,
            "record_count": 0,
            "records": [],
            "error": "invalid_hours",
        }

    # --------------------------------------------------------
    # 4. 计算最近若干小时的时间范围
    # --------------------------------------------------------

    end_time = datetime.now(timezone.utc)

    start_time = end_time - timedelta(
        hours=hours
    )

    # --------------------------------------------------------
    # 5. 从 SQLite 查询历史采样
    # --------------------------------------------------------

    state_store = DeviceStateStore()

    rows = state_store.get_temperature_history(
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        limit=1000,
    )

    # --------------------------------------------------------
    # 6. 转换为原有 Agent 使用的数据格式
    # --------------------------------------------------------

    records = [
        {
            "device_id": row["device_id"],
            "temperature": row["temperature"],
            "recorded_at": row["sampled_at"],
        }
        for row in reversed(rows)
    ]

    # --------------------------------------------------------
    # 7. 返回 Tool 结果
    # --------------------------------------------------------

    return {
        "success": True,
        "result_type": "temperature_history",
        "device_id": device_id,
        "hours": hours,
        "record_count": len(records),
        "records": records,
    }
