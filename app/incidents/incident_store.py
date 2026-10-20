
"""
设备故障 Incident 持久化管理。

支持：
1. E-101 编码器通信异常：fault
2. E-102 伺服驱动异常：fault
3. 温度异常：warning / critical
4. 相同故障去重
5. 温度 Warning 升级 Critical
6. 历史 Incident 兼容
7. 查询和关闭 Incident

说明：
fault 是非温度故障处置类别，
不是温度风险等级，也不代表高于 critical。
"""

import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


# ============================================================
# 1. 数据库路径与故障类型
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "incidents.db"


# 保留旧版温度 Incident 的默认故障键
INCIDENT_KEY = "temperature:overheat"

INCIDENT_KEYS = {
    "temperature:overheat",
    "encoder:communication",
    "servo:drive_fault",
}

# 只用于比较温度风险高低
RISK_LEVELS = {
    "warning": 1,
    "critical": 2,
}

# Incident 允许的处置类别
VALID_LEVELS = {
    "warning",
    "critical",
    "fault",
}


def utc_now() -> str:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 2. Incident Store
# ============================================================

class IncidentStore:

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

    # --------------------------------------------------------
    # 3. 数据库连接
    # --------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=10,
        )

        conn.row_factory = sqlite3.Row

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        return conn

    # --------------------------------------------------------
    # 4. 初始化数据库
    # --------------------------------------------------------

    def init_db(self) -> None:
        conn = self._connect()

        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS incidents (
                        incident_id TEXT PRIMARY KEY,
                        device_id TEXT NOT NULL,
                        incident_key TEXT NOT NULL,
                        alarm_code TEXT,
                        status TEXT NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'closed')),
                        created_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        highest_risk_level TEXT NOT NULL
                            DEFAULT 'warning'
                    )
                """)

                # 兼容缺少 highest_risk_level 的旧数据库
                columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(incidents)"
                    ).fetchall()
                }

                if "highest_risk_level" not in columns:
                    conn.execute("""
                        ALTER TABLE incidents
                        ADD COLUMN highest_risk_level TEXT
                        NOT NULL DEFAULT 'warning'
                    """)

                # 同一设备、同一故障类型：
                # 最多只能有一个 open Incident。
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        idx_unique_open_incident
                    ON incidents(device_id, incident_key)
                    WHERE status = 'open'
                """)

        finally:
            conn.close()

    # ========================================================
    # 5. 记录设备异常
    # ========================================================

    def record_anomaly(
        self,
        device_id: str,
        risk_level: str,
        alarm_code: str | None = None,
        incident_key: str = INCIDENT_KEY,
    ) -> dict:
        """
        创建或更新设备 Incident。

        温度异常：
            warning -> critical 可以升级。

        E-101 / E-102：
            使用 fault，不进行温度风险升级。

        同一设备 + 同一 incident_key：
            复用现有 open Incident。

        保留兼容：
            旧的 E-101 / E-102 Incident
            可能被记录为 critical。
            不修改其历史等级，也不重复创建。
        """

        # ----------------------------------------------------
        # 1. 参数标准化
        # ----------------------------------------------------

        device_id = device_id.strip().upper()
        risk_level = risk_level.strip().lower()
        incident_key = incident_key.strip().lower()

        alarm_code = (
            alarm_code.strip().upper() or None
            if alarm_code is not None
            else None
        )

        # ----------------------------------------------------
        # 2. 参数校验
        # ----------------------------------------------------

        if not device_id:
            raise ValueError("device_id 不能为空")

        if risk_level not in VALID_LEVELS:
            raise ValueError(
                "risk_level 只能是 warning、critical 或 fault"
            )

        if incident_key not in INCIDENT_KEYS:
            raise ValueError(
                f"不支持的故障类型：{incident_key}"
            )

        # 温度异常使用 warning / critical
        if incident_key == "temperature:overheat":
            if risk_level not in RISK_LEVELS:
                raise ValueError(
                    "温度异常只能使用 warning 或 critical"
                )

        # 非温度故障使用 fault
        else:
            if risk_level != "fault":
                raise ValueError(
                    "E-101、E-102 必须使用 fault"
                )

        # ----------------------------------------------------
        # 3. 查询活动 Incident
        # ----------------------------------------------------

        now = utc_now()
        conn = self._connect()

        try:
            with conn:
                # 在读写期间获取 SQLite 写锁，
                # 防止并发重复创建 Incident。
                conn.execute("BEGIN IMMEDIATE")

                existing = conn.execute(
                    """
                    SELECT *
                    FROM incidents
                    WHERE device_id = ?
                      AND incident_key = ?
                      AND status = 'open'
                    """,
                    (
                        device_id,
                        incident_key,
                    ),
                ).fetchone()

                # ------------------------------------------------
                # 情况 A：没有活动 Incident，新建
                # ------------------------------------------------

                if existing is None:
                    incident_id = (
                        "INC-" + uuid4().hex[:12].upper()
                    )

                    conn.execute(
                        """
                        INSERT INTO incidents (
                            incident_id,
                            device_id,
                            incident_key,
                            alarm_code,
                            status,
                            created_at,
                            last_seen_at,
                            highest_risk_level
                        )
                        VALUES (
                            ?, ?, ?, ?, 'open', ?, ?, ?
                        )
                        """,
                        (
                            incident_id,
                            device_id,
                            incident_key,
                            alarm_code,
                            now,
                            now,
                            risk_level,
                        ),
                    )

                    return {
                        "incident_id": incident_id,
                        "incident_key": incident_key,
                        "created_incident": True,
                        "risk_escalated": False,
                        "should_trigger": True,
                        "highest_risk_level": risk_level,
                    }

                # ------------------------------------------------
                # 情况 B：已有同类型活动 Incident
                # ------------------------------------------------

                incident_id = existing["incident_id"]
                old_risk = existing["highest_risk_level"]

                # E-101/E-102 没有温度风险升级。
                if incident_key != "temperature:overheat":
                    risk_escalated = False

                    # 兼容旧版曾保存为 critical 的 E-101/E-102。
                    # 不修改历史等级。
                    highest_risk = old_risk

                else:
                    # 温度异常才比较 warning / critical
                    if old_risk not in RISK_LEVELS:
                        raise ValueError(
                            "已有温度 Incident 的风险等级无效"
                        )

                    risk_escalated = (
                        RISK_LEVELS[risk_level]
                        > RISK_LEVELS[old_risk]
                    )

                    highest_risk = (
                        risk_level
                        if risk_escalated
                        else old_risk
                    )

                # ------------------------------------------------
                # 更新现有 Incident
                # ------------------------------------------------

                conn.execute(
                    """
                    UPDATE incidents
                    SET last_seen_at = ?,
                        highest_risk_level = ?,
                        alarm_code = COALESCE(?, alarm_code)
                    WHERE incident_id = ?
                    """,
                    (
                        now,
                        highest_risk,
                        alarm_code,
                        incident_id,
                    ),
                )

                return {
                    "incident_id": incident_id,
                    "incident_key": incident_key,
                    "created_incident": False,
                    "risk_escalated": risk_escalated,
                    "should_trigger": risk_escalated,
                    "highest_risk_level": highest_risk,
                }

        finally:
            conn.close()

    # ========================================================
    # 6. 查询指定 Incident
    # ========================================================

    def get_incident(
        self,
        incident_id: str,
    ) -> dict | None:

        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM incidents
                WHERE incident_id = ?
                """,
                (incident_id,),
            ).fetchone()

            return dict(row) if row else None

        finally:
            conn.close()

    # ========================================================
    # 7. 查询活动 Incident
    # ========================================================

    def get_active_incident(
        self,
        device_id: str,
        incident_key: str = INCIDENT_KEY,
    ) -> dict | None:
        """
        查询设备当前指定类型的活动 Incident。

        默认查询温度 Incident，
        保留原有调用兼容性。
        """

        device_id = device_id.strip().upper()
        incident_key = incident_key.strip().lower()

        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM incidents
                WHERE device_id = ?
                  AND incident_key = ?
                  AND status = 'open'
                """,
                (
                    device_id,
                    incident_key,
                ),
            ).fetchone()

            return dict(row) if row else None

        finally:
            conn.close()

    # ========================================================
    # 8. 关闭 Incident
    # ========================================================

    def close_incident(
        self,
        incident_id: str,
    ) -> bool:
        """
        关闭指定 Incident。

        当前只提供关闭操作，
        不在这里自行判定设备是否恢复。
        """

        conn = self._connect()

        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE incidents
                    SET status = 'closed'
                    WHERE incident_id = ?
                      AND status = 'open'
                    """,
                    (incident_id,),
                )

                return cursor.rowcount == 1

        finally:
            conn.close()

    # ========================================================
    # 9. 查询 Incident 列表
    # ========================================================

    def list_incidents(
        self,
        status: str | None = None,
        device_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        查询 Incident 列表。

        status:
            None   查询全部
            open   查询活动 Incident
            closed 查询已关闭 Incident

        device_id:
            可选的设备编号筛选
        """

        if not 1 <= limit <= 500:
            raise ValueError(
                "limit 必须在 1～500 之间"
            )

        if status not in (None, "open", "closed"):
            raise ValueError(
                "不支持的 Incident 状态"
            )

        sql = """
            SELECT *
            FROM incidents
            WHERE 1 = 1
        """

        parameters = []

        if status is not None:
            sql += " AND status = ?"
            parameters.append(status)

        if device_id is not None:
            device_id = device_id.strip().upper()

            if not device_id:
                raise ValueError(
                    "device_id 不能为空"
                )

            sql += " AND device_id = ?"
            parameters.append(device_id)

        sql += """
            ORDER BY created_at DESC, incident_id DESC
            LIMIT ?
        """

        parameters.append(limit)

        conn = self._connect()

        try:
            rows = conn.execute(
                sql,
                tuple(parameters),
            ).fetchall()

            return [
                dict(row)
                for row in rows
            ]

        finally:
            conn.close()
