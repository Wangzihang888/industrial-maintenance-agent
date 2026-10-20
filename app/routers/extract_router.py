
import json

from langchain_core.messages import ToolMessage

from app.state import AgentState


def has_fault_knowledge_result(state: AgentState) -> bool:
    """
    检查 Agent 是否已经收到故障知识库工具的返回。

    注意：
    收到返回结果，不等于一定有可靠知识。
    具体证据有效性仍由 RAG / Evidence Gate 判断。
    """

    for message in state.get("messages", []):
        if not isinstance(message, ToolMessage):
            continue

        if not isinstance(message.content, str):
            continue

        try:
            data = json.loads(message.content)
        except json.JSONDecodeError:
            continue

        if (
            isinstance(data, dict)
            and data.get("result_type") == "fault_knowledge"
        ):
            return True

    return False


def route_after_extract(state: AgentState) -> str:
    """
    决定是否已经收集足够信息，
    可以进入后续业务评估。

    自动任务：
        需要设备状态和 RAG 工具返回。
        不强制要求温度历史。

    其他任务：
        暂时保留原来的温度查询路由。
    """

    device_status = state.get("device_status")

    if state.get("execution_mode") == "automatic":

        if (
            device_status is not None
            and has_fault_knowledge_result(state)
        ):
            return "evaluate"

        return "agent"

    if (
        device_status is not None
        and "temperature_records" in state
    ):
        return "evaluate"

    return "agent"
