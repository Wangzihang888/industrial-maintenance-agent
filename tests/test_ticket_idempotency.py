
"""
正式维修工单幂等性回归测试。

验证：
1. 首次创建正式维修工单
2. 同一 Incident 重复创建时复用原工单
3. 不同 Incident 可以分别创建工单
4. 禁止同一 Incident 关联不同设备
5. SQLite 数据完整性

所有操作均使用临时 SQLite 数据库。
不调用真实 LLM，不修改项目正式 maintenance.db。
"""

import sqlite3
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def init_test_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)

    try:
        with conn:
            conn.execute("""
                CREATE TABLE maintenance_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    alarm_code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
    finally:
        conn.close()


def main() -> None:
    ticket_module = import_module(
        "app.tools.ticket_tool"
    )

    with TemporaryDirectory() as temp:
        db_path = Path(temp) / "maintenance_test.db"

        init_test_db(db_path)

        # 将工单工具的默认数据库替换为临时数据库
        with patch.object(
            ticket_module,
            "DB_PATH",
            db_path,
        ):

            first = ticket_module.create_maintenance_ticket.invoke({
                "device_id": "RB-001",
                "alarm_code": "E-101",
                "title": "编码器通信异常维修申请",
                "description": "隔离环境测试工单",
                "incident_id": "INC-TEST-001",
            })

            assert first["success"] is True
            assert first["created"] is True
            assert first["ticket"]["status"] == "OPEN"

            first_id = first["ticket"]["ticket_id"]

            print("[PASS] 首次创建正式工单")

            # 同一 Incident 再次调用
            second = ticket_module.create_maintenance_ticket.invoke({
                "device_id": "RB-001",
                "alarm_code": "E-101",
                "title": "编码器通信异常维修申请",
                "description": "隔离环境测试工单",
                "incident_id": "INC-TEST-001",
            })

            assert second["success"] is True
            assert second["created"] is False
            assert second["idempotent_reuse"] is True
            assert second["ticket"]["ticket_id"] == first_id

            print("[PASS] 同一 Incident 重复调用不生成新工单")

            third = ticket_module.create_maintenance_ticket.invoke({
                "device_id": "RB-002",
                "alarm_code": "E-102",
                "title": "伺服驱动异常维修申请",
                "description": "另一 Incident 测试",
                "incident_id": "INC-TEST-002",
            })

            assert third["success"] is True
            assert third["created"] is True
            assert third["ticket"]["ticket_id"] != first_id

            print("[PASS] 不同 Incident 可以独立创建工单")

            # 同一 Incident 不允许关联另一台设备
            try:
                ticket_module.create_maintenance_ticket.invoke({
                    "device_id": "RB-003",
                    "alarm_code": "E-101",
                    "title": "错误设备测试",
                    "description": "应该被拒绝",
                    "incident_id": "INC-TEST-001",
                })
            except ValueError:
                print("[PASS] 同一 Incident 的设备冲突被拒绝")
            else:
                raise AssertionError(
                    "同一 Incident 错误关联另一台设备"
                )

            conn = sqlite3.connect(db_path)

            try:
                total = conn.execute(
                    "SELECT COUNT(*) FROM maintenance_tickets"
                ).fetchone()[0]

                links = conn.execute(
                    "SELECT COUNT(*) FROM incident_ticket_links"
                ).fetchone()[0]

                integrity = conn.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]

                assert total == 2
                assert links == 2
                assert integrity == "ok"

                print("[PASS] 工单和 Incident 关联数量正确")
                print("[PASS] SQLite integrity_check：ok")

            finally:
                conn.close()

    print(
        "\n正式工单幂等性回归全部通过！"
        "\n临时数据库已清理。"
    )


if __name__ == "__main__":
    main()
