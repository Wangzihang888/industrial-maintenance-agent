
from langchain_core.messages import HumanMessage

from app.agent.llm import llm_with_tools


response = llm_with_tools.invoke([
    HumanMessage(
        content=(
            "请使用设备查询工具检查 RB-001 的"
            "当前运行状态。先调用工具，不要猜测温度。"
        )
    )
])

print("LLM 返回内容：", response.content)
print("工具调用：", response.tool_calls)

assert response.tool_calls, "LLM 没有产生工具调用"

tool_names = [
    item["name"]
    for item in response.tool_calls
]

assert "get_device_status" in tool_names, (
    f"没有调用预期的 Device Tool：{tool_names}"
)

print("测试通过：LLM Tool Calling 正常")
