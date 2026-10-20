
"""
企业设备智能运维 Agent
FastAPI 统一应用入口。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.dashboard_router import (
    router as dashboard_router,
)

from app.api.operations_router import (
    router as operations_router,
)

from app.api.approval_router import (
    router as approval_router,
)

from app.api.simulation_router import (
    router as simulation_router,
)

from app.api.chat_router import (
    router as chat_router,
)

# 新增：异常通知中心 API
from app.api.notification_router import (
    router as notification_router,
)


# ============================================================
# 1. 项目路径
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

WEB_DIR = PROJECT_ROOT / "app" / "web"
WEB_INDEX = WEB_DIR / "index.html"


# ============================================================
# 2. FastAPI 主应用
# ============================================================

app = FastAPI(
    title="Industrial Maintenance Agent",
    description="企业设备智能运维 Agent 双入口系统",
    version="1.0.0",
)


# ============================================================
# 3. 注册业务 Router
# ============================================================

# 设备状态、温度历史
app.include_router(dashboard_router)

# Incident、Agent Task 等业务查询
app.include_router(operations_router)

# 人工审批
app.include_router(approval_router)

# 设备模拟和持续运行控制
app.include_router(simulation_router)

# 人工 Agent 聊天
app.include_router(chat_router)

# 新增：异常通知中心
app.include_router(notification_router)


# ============================================================
# 4. 网页静态资源
# ============================================================

app.mount(
    "/static",
    StaticFiles(directory=WEB_DIR),
    name="static",
)


# ============================================================
# 5. 网页首页
# ============================================================

@app.get("/", include_in_schema=False)
def web_dashboard():
    return FileResponse(WEB_INDEX)


# ============================================================
# 6. 健康检查
# ============================================================

@app.get("/health", tags=["System"])
def health_check() -> dict:
    return {
        "status": "ok",
        "service": "industrial-maintenance-agent",
    }
