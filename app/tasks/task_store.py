
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "agent_tasks.db"

# fault 表示非温度故障处置类别
VALID_RISKS = {"warning", "critical", "fault"}

VALID_STATUSES = {
    "pending",
    "running",
    "waiting_approval",
    "completed",
    "failed",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:

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
    # 1. 初始化数据库并兼容旧版
    # ========================================================

    def init_db(self) -> None:
        conn = self._connect()

        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_tasks (
                        task_id TEXT PRIMARY KEY,
                        incident_id TEXT NOT NULL,
                        device_id TEXT NOT NULL,
                        risk_level TEXT NOT NULL
                            CHECK (
                                risk_level IN (
                                    'warning',
                                    'critical',
                                    'fault'
                                )
                            ),
                        thread_id TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK (
                                status IN (
                                    'pending',
                                    'running',
                                    'waiting_approval',
                                    'completed',
                                    'failed'
                                )
                            ),
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE (incident_id, risk_level)
                    )
                """)

                # 查看 SQLite 实际保存的建表语句
                row = conn.execute(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'agent_tasks'
                    """
                ).fetchone()

                schema = row["sql"]

                # 老版本不允许 fault，需要迁移
                if "'fault'" not in schema:
                    self._migrate_risk_constraint(conn)

        finally:
            conn.close()

    @staticmethod
    def _migrate_risk_constraint(
        conn: sqlite3.Connection,
    ) -> None:
        """
        SQLite 不能直接修改旧表 CHECK 约束。

        因此：
        1. 创建支持 fault 的新表
        2. 复制旧任务
        3. 删除旧表
        4. 将新表重命名

        整个过程由外层事务保护。
        """

        conn.execute("""
            CREATE TABLE agent_tasks_new (
                task_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                risk_level TEXT NOT NULL
                    CHECK (
                        risk_level IN (
                            'warning',
                            'critical',
                            'fault'
                        )
                    ),
                thread_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (
                        status IN (
                            'pending',
                            'running',
                            'waiting_approval',
                            'completed',
                            'failed'
                        )
                    ),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (incident_id, risk_level)
            )
        """)

        conn.execute("""
            INSERT INTO agent_tasks_new (
                task_id,
                incident_id,
                device_id,
                risk_level,
                thread_id,
                status,
                attempt_count,
                last_error,
                created_at,
                updated_at
            )
            SELECT
                task_id,
                incident_id,
                device_id,
                risk_level,
                thread_id,
                status,
                attempt_count,
                last_error,
                created_at,
                updated_at
            FROM agent_tasks
        """)

        conn.execute("DROP TABLE agent_tasks")

        conn.execute("""
            ALTER TABLE agent_tasks_new
            RENAME TO agent_tasks
        """)

    # ========================================================
    # 2. 创建或复用任务
    # ========================================================

    def enqueue_task(
        self,
        incident_id: str,
        device_id: str,
        risk_level: str,
    ) -> dict:

        incident_id = incident_id.strip()
        device_id = device_id.strip().upper()
        risk_level = risk_level.strip().lower()

        if not incident_id or not device_id:
            raise ValueError(
                "Incident ID 和 Device ID 不能为空"
            )

        if risk_level not in VALID_RISKS:
            raise ValueError("不支持的处置类别")

        task_id = "TASK-" + uuid4().hex[:12].upper()
        thread_id = f"auto:{task_id}"
        now = utc_now()

        conn = self._connect()

        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")

                existing = conn.execute(
                    """
                    SELECT *
                    FROM agent_tasks
                    WHERE incident_id = ?
                      AND risk_level = ?
                    """,
                    (incident_id, risk_level),
                ).fetchone()

                if existing is not None:
                    return {
                        **dict(existing),
                        "created": False,
                    }

                conn.execute(
                    """
                    INSERT INTO agent_tasks (
                        task_id,
                        incident_id,
                        device_id,
                        risk_level,
                        thread_id,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        task_id,
                        incident_id,
                        device_id,
                        risk_level,
                        thread_id,
                        now,
                        now,
                    ),
                )

                task = conn.execute(
                    """
                    SELECT *
                    FROM agent_tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()

                return {
                    **dict(task),
                    "created": True,
                }

        finally:
            conn.close()

    # ========================================================
    # 3. 原子领取任务
    # ========================================================

    def claim_task(self, task_id: str) -> bool:
        conn = self._connect()

        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE agent_tasks
                    SET status = 'running',
                        attempt_count = attempt_count + 1,
                        last_error = NULL,
                        updated_at = ?
                    WHERE task_id = ?
                      AND status = 'pending'
                    """,
                    (utc_now(), task_id),
                )

                return cursor.rowcount == 1

        finally:
            conn.close()

    # ========================================================
    # 4. 更新任务状态
    # ========================================================

    def transition_task(
        self,
        task_id: str,
        expected_status: str,
        new_status: str,
        error: str | None = None,
    ) -> bool:

        if (
            expected_status not in VALID_STATUSES
            or new_status not in VALID_STATUSES
        ):
            raise ValueError("不支持的任务状态")

        allowed = {
            "pending": {"running"},
            "running": {
                "waiting_approval",
                "completed",
                "failed",
            },
            "waiting_approval": {
                "completed",
                "failed",
            },
            "failed": {"pending"},
            "completed": set(),
        }

        if new_status not in allowed[expected_status]:
            raise ValueError(
                f"不允许状态转换："
                f"{expected_status} → {new_status}"
            )

        conn = self._connect()

        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE agent_tasks
                    SET status = ?,
                        last_error = ?,
                        updated_at = ?
                    WHERE task_id = ?
                      AND status = ?
                    """,
                    (
                        new_status,
                        error,
                        utc_now(),
                        task_id,
                        expected_status,
                    ),
                )

                return cursor.rowcount == 1

        finally:
            conn.close()

    # ========================================================
    # 5. 查询单个任务
    # ========================================================

    def get_task(
        self,
        task_id: str,
    ) -> dict | None:

        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM agent_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()

            return dict(row) if row else None

        finally:
            conn.close()

    def get_tasks_by_incident(
        self,
        incident_id: str,
    ) -> list[dict]:

        conn = self._connect()

        try:
            rows = conn.execute(
                """
                SELECT *
                FROM agent_tasks
                WHERE incident_id = ?
                ORDER BY created_at
                """,
                (incident_id,),
            ).fetchall()

            return [dict(row) for row in rows]

        finally:
            conn.close()

    # ========================================================
    # 6. 查询 Pending 任务
    # ========================================================

    def list_pending_tasks(
        self,
        limit: int = 20,
        device_id: str | None = None,
    ) -> list[dict]:

        if limit < 1:
            raise ValueError("limit 必须大于 0")

        parameters = []

        sql = """
            SELECT *
            FROM agent_tasks
            WHERE status = 'pending'
        """

        if device_id is not None:
            device_id = device_id.strip().upper()

            if not device_id:
                raise ValueError("device_id 不能为空")

            sql += " AND device_id = ?"
            parameters.append(device_id)

        sql += """
            ORDER BY created_at ASC, task_id ASC
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

    # ========================================================
    # 7. 查询任务列表
    # ========================================================

    def list_tasks(
        self,
        status: str | None = None,
        device_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:

        if not 1 <= limit <= 500:
            raise ValueError("limit 必须在 1～500 之间")

        if (
            status is not None
            and status not in VALID_STATUSES
        ):
            raise ValueError("不支持的任务状态")

        sql = """
            SELECT *
            FROM agent_tasks
            WHERE 1 = 1
        """

        parameters = []

        if status is not None:
            sql += " AND status = ?"
            parameters.append(status)

        if device_id is not None:
            device_id = device_id.strip().upper()

            if not device_id:
                raise ValueError("device_id 不能为空")

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
