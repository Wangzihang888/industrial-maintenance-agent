
from datetime import datetime
from typing import Literal
import math

from pydantic import BaseModel, Field, field_validator


class DeviceSnapshot(BaseModel):
    """
    设备在某个采样时刻的状态。

    只负责定义和校验数据；
    故障识别由 Monitoring Engine 完成。
    """

    # 基础状态
    device_id: str = Field(min_length=1)
    temperature: float
    current_alarm: str | None = None
    running_status: str = "running"
    sampled_at: datetime
    source: str = "device_simulator"

    # E-101：编码器通信
    encoder_comm_ok: bool = True
    encoder_error_count: int = Field(default=0, ge=0)

    # E-102：伺服驱动器
    servo_drive_status: Literal["normal", "fault"] = "normal"
    drive_alarm_subcode: str | None = None

    @field_validator("device_id", "running_status", "source")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空")
        return cleaned

    @field_validator("device_id")
    @classmethod
    def normalize_device_id(cls, value: str) -> str:
        return value.upper()

    @field_validator("current_alarm", "drive_alarm_subcode")
    @classmethod
    def normalize_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        return value.strip().upper() or None

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("temperature 必须是有限数值")
        return value

    @field_validator("sampled_at")
    @classmethod
    def validate_sample_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("sampled_at 必须包含时区")
        return value
