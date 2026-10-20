
"""
正式维修工单只读查询工具。

支持：
1. 根据 device_id 查询设备维修工单。
2. 根据 incident_id 查询关联的正式维修工单。
3. 同时指定 device_id、incident_id 进行精确筛选。

不执行 INSERT、UPDATE、DELETE。
不创建维修工单。
"""

import json
import sqlite3

from pathlib import Path

from langchain_core.tools import tool


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "maintenance.db"
)


def open_readonly_connection() -> sqlite3.Connection:
    """
    使用 SQLite 只读连接。

    mode=ro:
        禁止通过此连接修改数据库。

    URI 方式不会在数据库缺失时
    自动创建一个新的空数据库。
    """

    if not DB_PATH.is_file():
        raise FileNotFoundError(
            "maintenance.db 不存在"
        )

    connection = sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True,
        timeout=10,
    )

    connection.row_factory = sqlite3.Row

    return connection


@tool
def query_maintenance_tickets(
    device_id: str = "",
    incident_id: str = "",
) -> str:
    """
    查询正式维修工单及对应 Incident 关联。

    当用户询问设备维修工单、工单编号、
    工单是否创建、维修进度时使用。

    Args:
        device_id: 设备编号，例如 RGV-001。
        incident_id: Incident 编号，例如 INC-XXXXXXXXXXXX。
    """

    device_id = device_id.strip().upper()
    incident_id = incident_id.strip().upper()

    if not device_id and not incident_id:
        return json.dumps(
            {
                "success": False,
                "result_type": "maintenance_ticket_history",
                "error": "device_id_or_incident_id_required",
            },
            ensure_ascii=False,
        )

    try:
        connection = open_readonly_connection()

    except (FileNotFoundError, sqlite3.Error) as exc:
        return json.dumps(
            {
                "success": False,
                "result_type": "maintenance_ticket_history",
                "error": str(exc),
            },
            ensure_ascii=False,
        )

    try:
        # ====================================================
        # 1. 检查必要的数据表
        # ====================================================

        table_rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                  'maintenance_tickets',
                  'incident_ticket_links'
              )
            """
        ).fetchall()

        existing_tables = {
            row["name"]
            for row in table_rows
        }

        if "maintenance_tickets" not in existing_tables:
            return json.dumps(
                {
                    "success": False,
                    "result_type": "maintenance_ticket_history",
                    "error": "maintenance_tickets_table_missing",
                },
                ensure_ascii=False,
            )

        # ====================================================
        # 2. 根据关联表是否存在构造查询
        # ====================================================

        has_links = (
            "incident_ticket_links" in existing_tables
        )

        if not has_links and incident_id:
            return json.dumps(
                {
                    "success": False,
                    "result_type": "maintenance_ticket_history",
                    "error": "incident_ticket_links_table_missing",
                },
                ensure_ascii=False,
            )

        if has_links:
            sql = """
                SELECT
                    t.ticket_id,
                    t.device_id,
                    t.alarm_code,
                    t.title,
                    t.description,
                    t.status,
                    t.created_at,
                    l.incident_id
                FROM maintenance_tickets AS t
                LEFT JOIN incident_ticket_links AS l
                  ON t.ticket_id = l.ticket_id
                WHERE 1 = 1
            """
        else:
            # 兼容早期尚未建立关联表的旧数据。
            sql = """
                SELECT
                    t.ticket_id,
                    t.device_id,
                    t.alarm_code,
                    t.title,
                    t.description,
                    t.status,
                    t.created_at,
                    NULL AS incident_id
                FROM maintenance_tickets AS t
                WHERE 1 = 1
            """

        parameters = []

        # ====================================================
        # 3. 根据用户提供的条件筛选
        # ====================================================

        if device_id:
            sql += " AND t.device_id = ?"
            parameters.append(device_id)

        if incident_id:
            sql += " AND l.incident_id = ?"
            parameters.append(incident_id)

        sql += """
            ORDER BY
                t.created_at DESC,
                t.ticket_id DESC
            LIMIT 20
        """

        # ====================================================
        # 4. 执行只读 SQL
        # ====================================================

        rows = connection.execute(
            sql,
            tuple(parameters),
        ).fetchall()

        tickets = [
            dict(row)
            for row in rows
        ]

        # ====================================================
        # 5. 返回给 LLM
        # ====================================================

        return json.dumps(
            {
                "success": True,
                "result_type": "maintenance_ticket_history",
                "device_id": device_id or None,
                "incident_id": incident_id or None,
                "count": len(tickets),
                "tickets": tickets,
            },
            ensure_ascii=False,
            default=str,
        )

    except sqlite3.Error as exc:
        return json.dumps(
            {
                "success": False,
                "result_type": "maintenance_ticket_history",
                "error": str(exc),
            },
            ensure_ascii=False,
        )

    finally:
        connection.close()
