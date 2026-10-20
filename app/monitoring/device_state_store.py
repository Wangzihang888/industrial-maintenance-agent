
import sqlite3

from datetime import datetime, timezone
from pathlib import Path

from app.monitoring.device_state_models import DeviceSnapshot


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "device_state.db"

# 两张表都需要保存的新增字段
NEW_COLUMNS = {
    "encoder_comm_ok": "INTEGER",
    "encoder_error_count": "INTEGER",
    "servo_drive_status": "TEXT",
    "drive_alarm_subcode": "TEXT",
}


class DeviceStateStore:
    """
    保存设备最新状态和历史采样。

    支持：
    - 旧数据库自动增加新字段
    - 重复采样去重
    - 旧采样不覆盖最新状态
    - 查询最新设备状态
    - 查询温度历史
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=10,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        conn = self._connect()

        try:
            with conn:
                # 保留原有表结构
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS device_latest_state (
                        device_id TEXT PRIMARY KEY,
                        temperature REAL NOT NULL,
                        current_alarm TEXT,
                        running_status TEXT NOT NULL,
                        sampled_at TEXT NOT NULL,
                        source TEXT NOT NULL
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS temperature_history (
                        device_id TEXT NOT NULL,
                        sampled_at TEXT NOT NULL,
                        temperature REAL NOT NULL,
                        current_alarm TEXT,
                        running_status TEXT NOT NULL,
                        source TEXT NOT NULL,
                        PRIMARY KEY (device_id, sampled_at)
                    )
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_history_time
                    ON temperature_history(device_id, sampled_at)
                """)

                # 兼容已经存在的数据库
                for table_name in (
                    "device_latest_state",
                    "temperature_history",
                ):
                    existing_columns = {
                        row["name"]
                        for row in conn.execute(
                            f"PRAGMA table_info({table_name})"
                        )
                    }

                    for column_name, column_type in NEW_COLUMNS.items():
                        if column_name not in existing_columns:
                            conn.execute(
                                f"ALTER TABLE {table_name} "
                                f"ADD COLUMN {column_name} {column_type}"
                            )

        finally:
            conn.close()

    @staticmethod
    def _normalize_time(value: datetime) -> str:
        return value.astimezone(
            timezone.utc
        ).isoformat(timespec="microseconds")

    @staticmethod
    def _snapshot_values(snapshot: DeviceSnapshot) -> dict:
        """
        将 Pydantic 模型转换成 SQLite 可以保存的值。
        """
        return {
            "device_id": snapshot.device_id,
            "temperature": snapshot.temperature,
            "current_alarm": snapshot.current_alarm,
            "running_status": snapshot.running_status,
            "sampled_at": DeviceStateStore._normalize_time(
                snapshot.sampled_at
            ),
            "source": snapshot.source,
            "encoder_comm_ok": int(snapshot.encoder_comm_ok),
            "encoder_error_count": snapshot.encoder_error_count,
            "servo_drive_status": snapshot.servo_drive_status,
            "drive_alarm_subcode": snapshot.drive_alarm_subcode,
        }

    def save_snapshot(self, snapshot: DeviceSnapshot) -> dict:
        data = self._snapshot_values(snapshot)

        conn = self._connect()

        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")

                existing = conn.execute(
                    """
                    SELECT *
                    FROM temperature_history
                    WHERE device_id = ?
                      AND sampled_at = ?
                    """,
                    (
                        data["device_id"],
                        data["sampled_at"],
                    ),
                ).fetchone()

                duplicate = existing is not None

                if duplicate:
                    # 同一设备 + 同一时间必须对应同一份数据
                    same_data = all(
                        existing[key] == value
                        for key, value in data.items()
                    )

                    if not same_data:
                        raise ValueError(
                            "相同设备和采样时间对应不同的数据"
                        )

                else:
                    conn.execute(
                        """
                        INSERT INTO temperature_history (
                            device_id,
                            sampled_at,
                            temperature,
                            current_alarm,
                            running_status,
                            source,
                            encoder_comm_ok,
                            encoder_error_count,
                            servo_drive_status,
                            drive_alarm_subcode
                        )
                        VALUES (
                            :device_id,
                            :sampled_at,
                            :temperature,
                            :current_alarm,
                            :running_status,
                            :source,
                            :encoder_comm_ok,
                            :encoder_error_count,
                            :servo_drive_status,
                            :drive_alarm_subcode
                        )
                        """,
                        data,
                    )

                current = conn.execute(
                    """
                    SELECT sampled_at
                    FROM device_latest_state
                    WHERE device_id = ?
                    """,
                    (data["device_id"],),
                ).fetchone()

                is_newer = (
                    current is None
                    or data["sampled_at"] > current["sampled_at"]
                )

                if is_newer:
                    conn.execute(
                        """
                        INSERT INTO device_latest_state (
                            device_id,
                            temperature,
                            current_alarm,
                            running_status,
                            sampled_at,
                            source,
                            encoder_comm_ok,
                            encoder_error_count,
                            servo_drive_status,
                            drive_alarm_subcode
                        )
                        VALUES (
                            :device_id,
                            :temperature,
                            :current_alarm,
                            :running_status,
                            :sampled_at,
                            :source,
                            :encoder_comm_ok,
                            :encoder_error_count,
                            :servo_drive_status,
                            :drive_alarm_subcode
                        )
                        ON CONFLICT(device_id) DO UPDATE SET
                            temperature = excluded.temperature,
                            current_alarm = excluded.current_alarm,
                            running_status = excluded.running_status,
                            sampled_at = excluded.sampled_at,
                            source = excluded.source,
                            encoder_comm_ok = excluded.encoder_comm_ok,
                            encoder_error_count = excluded.encoder_error_count,
                            servo_drive_status = excluded.servo_drive_status,
                            drive_alarm_subcode = excluded.drive_alarm_subcode
                        """,
                        data,
                    )

                return {
                    "device_id": data["device_id"],
                    "sampled_at": data["sampled_at"],
                    "duplicate": duplicate,
                    "latest_updated": is_newer,
                }

        finally:
            conn.close()

    def get_latest_state(
        self,
        device_id: str,
    ) -> dict | None:
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM device_latest_state
                WHERE device_id = ?
                """,
                (device_id.strip().upper(),),
            ).fetchone()

            return dict(row) if row else None

        finally:
            conn.close()

    def get_temperature_history(
        self,
        device_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[dict]:

        if limit < 1:
            raise ValueError("limit 必须大于 0")

        if (
            start_time.tzinfo is None
            or start_time.utcoffset() is None
            or end_time.tzinfo is None
            or end_time.utcoffset() is None
        ):
            raise ValueError("查询时间必须包含时区")

        start = self._normalize_time(start_time)
        end = self._normalize_time(end_time)

        if start > end:
            raise ValueError("开始时间不能晚于结束时间")

        conn = self._connect()

        try:
            rows = conn.execute(
                """
                SELECT *
                FROM temperature_history
                WHERE device_id = ?
                  AND sampled_at >= ?
                  AND sampled_at <= ?
                ORDER BY sampled_at DESC
                LIMIT ?
                """,
                (
                    device_id.strip().upper(),
                    start,
                    end,
                    limit,
                ),
            ).fetchall()

            return [dict(row) for row in rows]

        finally:
            conn.close()
