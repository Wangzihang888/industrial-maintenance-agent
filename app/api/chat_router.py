
"""
人工主动询问 Agent 的 HTTP API。

接收：
- 用户问题 message
- 可选 thread_id

返回：
- Agent 最终回答
- 会话 thread_id
- 当前设备上下文

新增：
- 统计 ChatGraph 执行耗时
- 在 FastAPI 终端打印耗时日志

不改变原有聊天业务逻辑。
"""

import time

from uuid import uuid4

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel, Field

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
)

from app.agent.chat_graph import chat_graph


# ============================================================
# 1. 创建 Chat Router
# ============================================================

router = APIRouter(
    prefix="/api",
    tags=["Chat"],
)


# ============================================================
# 2. 请求数据模型
# ============================================================

class ChatRequest(BaseModel):

    message: str = Field(
        min_length=1,
        max_length=2000,
    )

    thread_id: str | None = None


# ============================================================
# 3. 人工 Agent 聊天接口
# ============================================================

@router.post("/chat")
def chat(request: ChatRequest):
    """
    处理一次人工 Agent 对话。

    主要流程：

    1. 接收并校验用户问题
    2. 创建或复用 thread_id
    3. 调用 LangGraph
    4. 统计 Agent 执行耗时
    5. 获取最终 AIMessage
    6. 返回回答及设备上下文
    """

    # --------------------------------------------------------
    # 1. 清理用户问题
    # --------------------------------------------------------

    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=422,
            detail="message_cannot_be_empty",
        )

    # --------------------------------------------------------
    # 2. 创建或复用会话 ID
    # --------------------------------------------------------

    thread_id = (
        request.thread_id
        or "chat:" + uuid4().hex
    )

    if not thread_id.startswith("chat:"):
        raise HTTPException(
            status_code=422,
            detail="invalid_chat_thread_id",
        )

    # --------------------------------------------------------
    # 3. LangGraph 运行配置
    # --------------------------------------------------------

    config = {
        "configurable": {
            "thread_id": thread_id,
        },
        "recursion_limit": 30,
    }

    # --------------------------------------------------------
    # 4. 开始计时
    # --------------------------------------------------------

    start_time = time.perf_counter()

    try:

        # ----------------------------------------------------
        # 5. 执行人工 Agent 工作流
        # ----------------------------------------------------

        result = chat_graph.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=message
                    )
                ],
            },
            config=config,
        )

    finally:

        # ----------------------------------------------------
        # 6. 计算执行耗时
        # ----------------------------------------------------

        elapsed = (
            time.perf_counter()
            - start_time
        )

        print(
            "[Chat Agent] "
            f"thread_id={thread_id} | "
            f"耗时={elapsed:.2f}秒",
            flush=True,
        )

    # --------------------------------------------------------
    # 7. 获取最终 AIMessage
    # --------------------------------------------------------

    last_message = result["messages"][-1]

    if not isinstance(
        last_message,
        AIMessage,
    ):
        raise RuntimeError(
            "聊天工作流未返回 AIMessage"
        )

    if last_message.tool_calls:
        raise RuntimeError(
            "聊天工作流尚未完成工具调用"
        )

    # --------------------------------------------------------
    # 8. 返回聊天结果
    # --------------------------------------------------------

    return {
        "success": True,
        "thread_id": thread_id,
        "answer": last_message.content,
        "current_device_id": result.get(
            "current_device_id"
        ),
        "current_incident_id": result.get(
            "current_incident_id"
        ),
    }
