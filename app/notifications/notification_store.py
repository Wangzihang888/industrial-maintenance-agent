
"""
系统异常通知持久化存储。

每个自动 Agent Task 最多生成一条通知。

通知和维修审批相互独立：
- 通知记录生成后可以持续查看
- Task 完成不会删除通知
- Incident 恢复不会删除通知
"""

import sqlite3

from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = (
    PROJECT_ROOT / "data" / "notifications.db"
)


class NotificationStore:

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

    # ========================================================
    # 1. 初始化数据库
    # ========================================================

    def init_db(self) -> None:
        conn = self._connect()

        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        task_id TEXT PRIMARY KEY,
                        incident_id TEXT NOT NULL,
                        device_id TEXT NOT NULL,
                        notification_level TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS
                        idx_notifications_created
                    ON notifications(created_at DESC)
                """)

        finally:
            conn.close()

    # ========================================================
    # 2. 保存通知
    # ========================================================

    def save_notification(
        self,
        task_id: str,
        incident_id: str,
        device_id: str,
        notification_level: str,
        message: str,
    ) -> dict:
        """
        按 task_id 去重。

        同一 Task 如果因为 LangGraph 重试而再次
        执行通知节点，不会重复插入通知。
        """

        task_id = task_id.strip()
        incident_id = incident_id.strip()
        device_id = device_id.strip().upper()
        notification_level = (
            notification_level.strip().lower()
        )
        message = message.strip()

        if not all((
            task_id,
            incident_id,
            device_id,
            notification_level,
            message,
        )):
            raise ValueError("通知必要字段不能为空")

        if notification_level not in (
            "warning",
            "critical",
            "fault",
        ):
            raise ValueError("不支持的通知类别")

        created_at = (
            datetime.now(timezone.utc).isoformat()
        )

        conn = self._connect()

        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO notifications (
                        task_id,
                        incident_id,
                        device_id,
                        notification_level,
                        message,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        incident_id,
                        device_id,
                        notification_level,
                        message,
                        created_at,
                    ),
                )

                row = conn.execute(
                    """
                    SELECT *
                    FROM notifications
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()

                return {
                    **dict(row),
                    "created": cursor.rowcount == 1,
                }

        finally:
            conn.close()

    # ========================================================
    # 3. 查询通知列表
    # ========================================================

    def list_notifications(
        self,
        device_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:

        if not 1 <= limit <= 200:
            raise ValueError("limit 必须在 1～200 之间")

        sql = """
            SELECT *
            FROM notifications
            WHERE 1 = 1
        """

        parameters = []

        if device_id is not None:
            device_id = device_id.strip().upper()

            if not device_id:
                raise ValueError("设备编号不能为空")

            sql += " AND device_id = ?"
            parameters.append(device_id)

        sql += """
            ORDER BY created_at DESC, task_id DESC
            LIMIT ?
        """

        parameters.append(limit)

        conn = self._connect()

        try:
            rows = conn.execute(
                sql,
                tuple(parameters),
            ).fetchall()

            return [dict(row) for row in rows]

        finally:
            conn.close()
