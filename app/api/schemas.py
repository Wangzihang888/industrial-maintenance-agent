
from pydantic import BaseModel, StrictBool


class ApprovalRequest(BaseModel):
    """
    人工审批请求。

    approved=True：批准
    approved=False：拒绝
    """

    approved: StrictBool
