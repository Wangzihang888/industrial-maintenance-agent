
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "maintenance.db"
)


@tool
def create_maintenance_ticket(
    device_id: str,
    alarm_code: str | None,
    title: str,
    description: str,
    incident_id: str | None = None,
) -> dict[str, Any]:
    """
    创建正式维修工单。

    仅允许由人工审批通过后的 Workflow 调用。

    自动任务提供 incident_id 时：
        同一 Incident 最多创建一张正式工单。

    incident_id=None：
        保留旧版调用兼容性，但不具备
        Incident 级别的幂等保护。
    """

    # ========================================================
    # 1. 参数标准化
    # ========================================================

    device_id = device_id.strip().upper()
    title = title.strip()
    description = description.strip()

    if not device_id:
        raise ValueError("device_id 不能为空")

    if not title or not description:
        raise ValueError("工单标题和描述不能为空")

    if alarm_code is not None:
        alarm_code = alarm_code.strip().upper() or None

    if incident_id is not None:
        incident_id = incident_id.strip()

        if not incident_id:
            raise ValueError("incident_id 不能为空")

    # 为了兼容旧版数据库可能存在的 NOT NULL 约束，
    # 使用明确的无报警标记，不伪造 E-103。
    stored_alarm_code = alarm_code or "NO_ALARM"

    # ========================================================
    # 2. 生成正式工单信息
    # ========================================================

    now = datetime.now(timezone.utc)

    ticket_id = (
        "WO-"
        f"{now.strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid.uuid4().hex[:6]}"
    )

    status = "OPEN"

    created_at = now.isoformat(
        timespec="seconds"
    )

    # ========================================================
    # 3. 建立数据库连接
    # ========================================================

    connection = sqlite3.connect(
        DB_PATH,
        timeout=10,
    )

    connection.row_factory = sqlite3.Row

    try:
        # ====================================================
        # 4. 在一个事务里处理查询与写入
        # ====================================================

        with connection:

            connection.execute("BEGIN IMMEDIATE")

            # 同一个 SQLite 数据库中的关联表。
            # incident_id 唯一，保证同一 Incident
            # 不会关联多张正式维修工单。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS
                    incident_ticket_links (
                        incident_id TEXT PRIMARY KEY,
                        ticket_id TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    )
                """
            )

            # =================================================
            # 5. 已存在工单时直接复用
            # =================================================

            if incident_id is not None:

                existing = connection.execute(
                    """
                    SELECT
                        t.ticket_id,
                        t.device_id,
                        t.alarm_code,
                        t.title,
                        t.description,
                        t.status,
                        t.created_at
                    FROM incident_ticket_links AS l
                    JOIN maintenance_tickets AS t
                      ON t.ticket_id = l.ticket_id
                    WHERE l.incident_id = ?
                    """,
                    (incident_id,),
                ).fetchone()

                if existing is not None:

                    if existing["device_id"] != device_id:
                        raise ValueError(
                            "Incident 已关联其他设备工单"
                        )

                    return {
                        "success": True,
                        "result_type": "ticket_created",
                        "created": False,
                        "idempotent_reuse": True,
                        "incident_id": incident_id,
                        "ticket": dict(existing),
                    }

                # 如果关联记录存在，但正式工单缺失，
                # 不能将其误认为从未创建过。
                link = connection.execute(
                    """
                    SELECT ticket_id
                    FROM incident_ticket_links
                    WHERE incident_id = ?
                    """,
                    (incident_id,),
                ).fetchone()

                if link is not None:
                    raise RuntimeError(
                        "Incident 已关联工单，但工单数据缺失"
                    )

            # =================================================
            # 6. 创建正式维修工单
            # =================================================

            connection.execute(
                """
                INSERT INTO maintenance_tickets (
                    ticket_id,
                    device_id,
                    alarm_code,
                    title,
                    description,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    device_id,
                    stored_alarm_code,
                    title,
                    description,
                    status,
                    created_at,
                ),
            )

            # =================================================
            # 7. 建立 Incident 与 Ticket 的关联
            # =================================================

            if incident_id is not None:

                connection.execute(
                    """
                    INSERT INTO incident_ticket_links (
                        incident_id,
                        ticket_id,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        incident_id,
                        ticket_id,
                        created_at,
                    ),
                )

        # 正常退出 with 后，事务已经提交。
        return {
            "success": True,
            "result_type": "ticket_created",
            "created": True,
            "idempotent_reuse": False,
            "incident_id": incident_id,
            "ticket": {
                "ticket_id": ticket_id,
                "device_id": device_id,
                "alarm_code": stored_alarm_code,
                "title": title,
                "description": description,
                "status": status,
                "created_at": created_at,
            },
        }

    finally:
        connection.close()
