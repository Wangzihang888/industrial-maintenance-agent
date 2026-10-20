
import json

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "data" / "devices.json"


def load_device_config(
    device_id: str,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict:
    """
    根据设备编号读取静态设备配置。

    返回：
        device_id
        device_name
        device_type
        temperature_warning
        temperature_limit
    """

    normalized_id = device_id.strip().upper()

    if not normalized_id:
        raise ValueError("device_id 不能为空")

    path = Path(config_path)

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        devices = json.load(file)

    if not isinstance(devices, dict):
        raise ValueError("devices.json 顶层必须是对象")

    device = devices.get(normalized_id)

    if not isinstance(device, dict):
        raise ValueError(
            f"设备不存在：{normalized_id}"
        )

    if device.get("device_id") != normalized_id:
        raise ValueError(
            f"设备配置编号不一致：{normalized_id}"
        )

    warning = float(device["temperature_warning"])
    limit = float(device["temperature_limit"])

    import math

    if not (
        math.isfinite(warning)
        and math.isfinite(limit)
        and warning < limit
    ):
        raise ValueError(
            f"设备温度阈值无效：{normalized_id}"
        )

    return {
        "device_id": normalized_id,
        "device_name": device["device_name"],
        "device_type": device["device_type"],
        "temperature_warning": warning,
        "temperature_limit": limit,
    }
