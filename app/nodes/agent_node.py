
from langchain_core.messages import SystemMessage

from app.state import AgentState
from app.agent.llm import llm_with_tools


def build_agent_context(state: AgentState) -> str:
    """
    将已有的结构化业务结果提供给 LLM。

    不负责故障检测、风险分级或审批决策。
    """

    context_parts = []

    # 1. RAG 维修知识
    knowledge = state.get("fault_knowledge")

    if knowledge:
        context_parts.append(
            "企业维修知识库结果：\n"
            f"{knowledge}\n"
            "只能依据可靠证据提出维修建议，"
            "不能把可能原因描述为已确认根因。"
        )

    # 2. 温度分析（主要用于人工温度查询）
    temperature_status = state.get("temperature_status")

    if temperature_status is not None:
        context_parts.append(
            "Python 温度分析结果：\n"
            f"状态：{temperature_status}\n"
            f"预警阈值：{state.get('temperature_warning')}℃\n"
            f"安全限值：{state.get('temperature_limit')}℃\n"
            f"综合最高温度：{state.get('max_temperature')}℃\n"
            "不要自行重新判定风险等级。"
        )

    # 3. 已生成的通知
    notification_message = state.get(
        "notification_message"
    )

    if notification_message:
        context_parts.append(
            f"系统通知结果：{notification_message}"
        )

    # 4. 工单决策
    if state.get("need_ticket") is not None:
        context_parts.append(
            "维修工单状态：\n"
            f"需要工单：{state.get('need_ticket')}\n"
            f"工单状态：{state.get('ticket_status')}"
        )

    # 5. 工单创建结果
    if state.get("ticket_created") is not None:
        context_parts.append(
            "正式工单创建结果：\n"
            f"是否成功：{state.get('ticket_created')}\n"
            f"工单编号：{state.get('ticket_id')}"
        )

    return "\n\n".join(context_parts)


def agent_node(state: AgentState) -> dict:
    """
    Agent 节点：

    1. 构造业务上下文
    2. 自动任务要求使用查询工具
    3. 调用 LLM
    4. 返回模型消息

    不创建正式维修工单。
    """

    context = build_agent_context(state)
    messages_for_llm = []

    if state.get("execution_mode") == "automatic":
        system_prompt = (
            "你是工业设备智能运维 Agent。\n"
            "当前任务由设备监控系统自动触发。\n"
            "必须优先使用设备状态查询工具，"
            "并使用故障知识库工具查询本次 Incident "
            "对应的故障代码。\n"
            "只有温度异常任务才需要重点查询温度历史。\n"
            "本次故障以任务提供的 Incident 信息为准，"
            "不能用设备最新报警覆盖历史故障。\n"
            "如果维修知识证据不足，必须说明不确定性，"
            "不得编造故障原因。\n"
            "不要调用任何创建维修工单的工具。\n"
            "不要自行决定或改变触发风险等级。"
        )
    else:
        system_prompt = (
            "你是工业设备智能运维助手。"
            "回答应基于实际工具结果和可靠维修知识，"
            "不要编造故障、设备状态或维修记录。"
        )

    if context:
        system_prompt += (
            "\n\n已经获得的结构化业务信息：\n"
            + context
        )

    messages_for_llm.append(
        SystemMessage(content=system_prompt)
    )
    messages_for_llm.extend(state["messages"])

    response = llm_with_tools.invoke(
        messages_for_llm
    )

    # 自动任务如果未完成取证就直接回答，
    # tools_condition 会让 Graph 直接结束。
    # 因此明确报错，交由 AgentRunner 标记任务失败。
    #
    # 这里的检查只防止“无工具调用就提前结束”。
    # RAG 是否真正可靠，还需要实际检索测试。
    if (
        state.get("execution_mode") == "automatic"
        and not response.tool_calls
    ):
        raise RuntimeError(
            "自动 Agent 未继续调用必要工具，"
            "不能直接结束故障处置流程"
        )

    return {
        "messages": [response]
    }
