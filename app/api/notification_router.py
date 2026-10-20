
"""
Web 异常通知中心 API。

只负责查询通知记录。
不创建通知，也不修改审批状态。
"""

from fastapi import APIRouter, Query

from app.notifications.notification_store import (
    NotificationStore,
)


router = APIRouter(
    prefix="/api/notifications",
    tags=["Notifications"],
)


@router.get("")
def list_notifications(
    device_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    查询最近的系统异常通知。

    可以根据 device_id 筛选，
    默认返回最近 50 条。
    """

    store = NotificationStore()

    notifications = store.list_notifications(
        device_id=device_id,
        limit=limit,
    )

    return {
        "success": True,
        "count": len(notifications),
        "notifications": notifications,
    }
