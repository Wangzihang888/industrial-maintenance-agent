import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "maintenance.db"
)


def init_database() -> None:
    """
    初始化设备运维项目使用的 SQLite 数据库。

    当前包含：

    1. temperature_records
       设备历史温度记录

    2. maintenance_tickets
       维修工单
    """

    connection = sqlite3.connect(
        DB_PATH
    )

    try:
        cursor = connection.cursor()

        # ====================================================
        # 1. 历史温度表
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS temperature_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                temperature REAL NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )


        # ----------------------------------------------------
        # 测试环境下重新生成温度数据
        # ----------------------------------------------------

        cursor.execute(
            """
            DELETE FROM temperature_records
            """
        )


        now = datetime.now()


        records = [

            # =================================================
            # RB-001
            #
            # Critical 测试设备
            #
            # warning = 65℃
            # limit   = 75℃
            # =================================================

            (
                "RB-001",
                68.5,
                now - timedelta(hours=20),
            ),

            (
                "RB-001",
                72.3,
                now - timedelta(hours=12),
            ),

            (
                "RB-001",
                78.6,
                now - timedelta(hours=6),
            ),

            (
                "RB-001",
                82.1,
                now - timedelta(hours=2),
            ),


            # =================================================
            # RB-002
            #
            # Normal 测试设备
            #
            # warning = 65℃
            # limit   = 75℃
            # =================================================

            (
                "RB-002",
                56.4,
                now - timedelta(hours=8),
            ),

            (
                "RB-002",
                58.2,
                now - timedelta(hours=2),
            ),


            # =================================================
            # RB-003
            #
            # Warning 测试设备
            #
            # warning = 65℃
            # limit   = 75℃
            # =================================================

            (
                "RB-003",
                67.2,
                now - timedelta(hours=12),
            ),

            (
                "RB-003",
                69.1,
                now - timedelta(hours=6),
            ),

            (
                "RB-003",
                70.0,
                now - timedelta(hours=2),
            ),
        ]


        # ----------------------------------------------------
        # 批量写入历史温度
        # ----------------------------------------------------

        cursor.executemany(
            """
            INSERT INTO temperature_records (
                device_id,
                temperature,
                recorded_at
            )
            VALUES (?, ?, ?)
            """,
            [
                (
                    device_id,
                    temperature,
                    recorded_at.isoformat(
                        timespec="seconds"
                    ),
                )

                for (
                    device_id,
                    temperature,
                    recorded_at,
                )

                in records
            ],
        )


        # ====================================================
        # 2. 维修工单表
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL UNIQUE,
                device_id TEXT NOT NULL,
                alarm_code TEXT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


        # ----------------------------------------------------
        # 开发测试阶段：
        #
        # 每次初始化数据库时清空测试工单，
        # 保证测试结果可以重复。
        # ----------------------------------------------------

        cursor.execute(
            """
            DELETE FROM maintenance_tickets
            """
        )


        # ====================================================
        # 3. 提交事务
        # ====================================================

        connection.commit()


        print(
            f"Database initialized: {DB_PATH}"
        )


        print(
            f"Inserted temperature records: "
            f"{len(records)}"
        )


        print(
            "Maintenance tickets reset."
        )


    finally:

        connection.close()


if __name__ == "__main__":

    init_database()