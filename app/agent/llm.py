
"""
Agent LLM 初始化与工具权限配置。

query_tools：
    只读查询工具，允许 LLM 自主调用。

action_tools：
    业务写入工具，不绑定到 LLM。
    只能由受控 Workflow 在通过业务校验
    和人工审批后调用。
"""

from langchain_openai import ChatOpenAI

from app.config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_CHAT_MODEL,
)

from app.tools.device_tool import (
    get_device_status,
)

from app.tools.history_tool import (
    query_temperature_history,
)

from app.tools.rag_tool import (
    search_fault_knowledge,
)

from app.tools.incident_query_tool import (
    query_device_incidents,
)

from app.tools.maintenance_query_tool import (
    query_maintenance_tickets,
)

from app.tools.ticket_tool import (
    create_maintenance_ticket,
)


# ============================================================
# 1. Read-only Query Tools
# ============================================================

query_tools = [
    get_device_status,
    query_temperature_history,
    search_fault_knowledge,
    query_device_incidents,
    query_maintenance_tickets,
]


# ============================================================
# 2. Action Tools
# ============================================================

# 注意：
# 不要把这个列表添加到 llm.bind_tools() 中。
#
# 工单创建必须经过 Workflow 的确定性业务校验
# 与人工审批。

action_tools = [
    create_maintenance_ticket,
]


# ============================================================
# 3. LLM 初始化
# ============================================================

llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
    model=DASHSCOPE_CHAT_MODEL,
    temperature=0,
)


# ============================================================
# 4. 仅向 LLM 暴露查询工具
# ============================================================

llm_with_tools = llm.bind_tools(
    query_tools
)
