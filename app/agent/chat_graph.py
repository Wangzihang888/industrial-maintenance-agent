
"""
人工聊天专用 LangGraph。

功能：
1. 维护设备上下文及 Incident 业务记忆
2. 支持多轮自然语言对话
3. 调用只读查询工具
4. 统计 LLM 和工具执行耗时
5. 规范模拟数据、历史故障和维修知识的回答

正式维修工单创建不属于此 Graph。
"""

import json
import re
import sqlite3
import time

from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import (
    AnyMessage,
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from langchain_core.runnables import RunnableConfig

from langgraph.graph import (
    StateGraph,
    START,
)

from langgraph.graph.message import add_messages

from langgraph.prebuilt import (
    ToolNode,
    tools_condition,
)

from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.llm import (
    llm_with_tools,
    query_tools,
)


# ============================================================
# 1. Chat State
# ============================================================

class ChatState(TypedDict, total=False):

    messages: Annotated[
        list[AnyMessage],
        add_messages,
    ]

    current_device_id: str | None

    current_incident_id: str | None

    context_start_index: int


# ============================================================
# 2. 识别设备编号
# ============================================================

DEVICE_PATTERN = re.compile(
    r"\b(?:RB|RGV)-\d{3}\b",
    re.IGNORECASE,
)


def prepare_chat_node(
    state: ChatState,
) -> dict:
    """
    用户明确切换设备时：

    1. 更新设备 ID
    2. 清除旧 Incident 记忆
    3. 切断旧设备的聊天上下文

    未明确切换时保留上下文。
    """

    messages = state.get(
        "messages",
        [],
    )

    latest_index = None

    for index in range(
        len(messages) - 1,
        -1,
        -1,
    ):
        if isinstance(
            messages[index],
            HumanMessage,
        ):
            latest_index = index
            break

    if latest_index is None:
        return {}

    latest_message = messages[latest_index]

    if not isinstance(
        latest_message.content,
        str,
    ):
        return {}

    matches = {
        device_id.upper()
        for device_id in DEVICE_PATTERN.findall(
            latest_message.content
        )
    }

    # 同时谈论多个设备时不自动切换。
    if len(matches) != 1:
        return {}

    new_device_id = next(
        iter(matches)
    )

    if new_device_id == state.get(
        "current_device_id"
    ):
        return {}

    return {
        "current_device_id": new_device_id,
        "current_incident_id": None,
        "context_start_index": latest_index,
    }


# ============================================================
# 3. 构建聊天上下文
# ============================================================

def build_chat_messages(
    state: ChatState,
) -> list[AnyMessage]:
    """
    旧轮次：
        只保留最近自然语言问答。

    当前轮次：
        保留 HumanMessage、AI 工具调用及 ToolMessage。

    切换设备：
        不引用之前设备的旧对话上下文。
    """

    messages = state.get(
        "messages",
        [],
    )

    if not messages:
        return [
            SystemMessage(
                content="你是企业设备运维查询助手。"
            )
        ]

    latest_human_index = next(
        (
            index
            for index in range(
                len(messages) - 1,
                -1,
                -1,
            )
            if isinstance(
                messages[index],
                HumanMessage,
            )
        ),
        0,
    )

    context_start = max(
        0,
        min(
            state.get(
                "context_start_index",
                0,
            ),
            latest_human_index,
        ),
    )

    previous_messages = messages[
        context_start:latest_human_index
    ]

    current_turn_messages = messages[
        latest_human_index:
    ]

    recent_dialogue = [
        message
        for message in previous_messages
        if isinstance(
            message,
            HumanMessage,
        )
        or (
            isinstance(message, AIMessage)
            and not message.tool_calls
            and isinstance(message.content, str)
            and message.content.strip()
        )
    ][-8:]

    device_id = state.get(
        "current_device_id"
    )

    incident_id = state.get(
        "current_incident_id"
    )

    # ========================================================
    # System Prompt：完整业务约束
    # ========================================================

    system_prompt = f"""
你是企业设备智能运维系统的人工查询 Agent。

【当前结构化业务记忆】
设备 ID：{device_id or "尚未确定"}
Incident ID：{incident_id or "尚未确定"}

【查询规则】
1. 查询真实设备状态、温度、Incident、Agent Task
   和正式维修工单时，必须使用对应查询工具。
2. 不得编造设备状态、故障编号、任务状态和工单编号。
3. 当用户使用“它”“这台设备”等指代时，
   优先使用当前设备上下文。
4. 当用户使用“这次故障”“对应工单”等指代时，
   如果当前 Incident ID 已确定，优先使用该 ID
   进行精确查询。
5. 如果一台设备有多个 Incident 且用户未明确
   指定哪一个，不得擅自选择；应请求澄清。
6. 切换设备后，不得继续引用上一台设备的数据。
7. Tool 的查询结果优先于历史聊天内容。
8. 工单 OPEN 表示正式工单仍待处理，
   Agent Task completed 不代表设备已维修完成。
9. 查询不到记录时明确说明，不得补造数据。

【模拟数据与时效性】
1. 本项目的数据可能由 device_simulator 等模拟程序产生。
   如果工具结果的 source 为 device_simulator，
   必须称为“模拟采样”或“测试记录”，
   不得描述成真实工厂生产事故。
   若数据来源未明确，应说明来源未确认。
2. 设备状态工具返回的是“最新保存的采样状态”，
   不等同于当前实时状态。
   可以说明采样时间、当时上报的 running_status 和温度；
   未查询到实时在线状态时，
   不得断言设备此刻正在运行。
3. Incident 发生次数可以按数据库记录统计，
   但若来自演示模拟或反复重演，
   不得据此认定设备真实存在反复硬件故障，
   也不得推断真实故障率。

【历史业务规则兼容】
1. 现行规则：
   E-101 编码器通信异常、E-102 伺服驱动异常归类为 fault；
   温度异常才使用 warning / critical。
2. 旧版 E-101 / E-102 记录可能保留
   highest_risk_level=critical。
   这是历史分类遗留，
   不代表实际从 fault 升级为 critical。
   除非有明确的状态变更证据，
   不得写成“故障升级”。
3. Incident closed 表示对应监控故障信号
   已满足恢复条件。
   Agent Task completed 仅表示自动处置工作流完成。
   维修工单是否完工应以工单自身状态为准。

【维修知识证据】
1. 查询故障含义、排查步骤和维修建议时，
   应使用故障知识库工具。
2. 严格区分手册明确记载的结论、
   一般性风险推断和未知信息。
3. 不要将可能的后果说成手册原文。
   无证据时不要编造故障含义。

【执行权限】
当前工作流只允许信息查询。
不要创建、关闭或修改 Incident、Task 或正式工单。
如果用户提出维修申请，
可以说明需要进入受控申请与审批流程；
当前图尚未执行该动作。

【回答要求】
使用中文，准确、简洁。
区分事实、推断和未知信息。
""".strip()

    return [
        SystemMessage(
            content=system_prompt,
        ),
        *recent_dialogue,
        *current_turn_messages,
    ]


# ============================================================
# 4. Chat Agent Node
# ============================================================

def chat_agent_node(
    state: ChatState,
) -> dict:
    """
    调用 LLM，并统计执行时间。

    不改变原有 Tool Calling 逻辑。
    """

    messages_for_llm = build_chat_messages(
        state
    )

    start_time = time.perf_counter()

    try:
        response = llm_with_tools.invoke(
            messages_for_llm
        )

    finally:
        elapsed = (
            time.perf_counter()
            - start_time
        )

        print(
            f"[Chat LLM] 耗时={elapsed:.2f}秒",
            flush=True,
        )

    print(
        "[Chat LLM] 调用结果="
        + (
            "请求工具"
            if response.tool_calls
            else "最终回答"
        ),
        flush=True,
    )

    return {
        "messages": [
            response
        ]
    }


# ============================================================
# 5. Tools Node 性能计时
# ============================================================

original_tool_node = ToolNode(
    query_tools
)


def timed_tools_node(
    state: ChatState,
    config: RunnableConfig,
) -> dict:
    """
    复用原有 ToolNode。

    只统计本批工具总耗时，
    不修改工具集合或工具返回结果。
    """

    start_time = time.perf_counter()

    try:
        return original_tool_node.invoke(
            state,
            config=config,
        )

    finally:
        elapsed = (
            time.perf_counter()
            - start_time
        )

        print(
            f"[Chat Tools] 耗时={elapsed:.2f}秒",
            flush=True,
        )


# ============================================================
# 6. 从 ToolMessage 同步 Incident 业务记忆
# ============================================================

def sync_business_memory_node(
    state: ChatState,
) -> dict:
    """
    只采信最近一次工具调用批次中的
    incident_history 结果。

    必须校验记录所属设备，
    防止不同设备的 Incident 混淆。
    """

    messages = state.get(
        "messages",
        [],
    )

    current_device_id = state.get(
        "current_device_id"
    )

    if not current_device_id:
        return {}

    last_call_index = None
    tool_call_ids = set()

    for index in range(
        len(messages) - 1,
        -1,
        -1,
    ):
        message = messages[index]

        if (
            isinstance(message, AIMessage)
            and message.tool_calls
        ):
            last_call_index = index

            tool_call_ids = {
                call["id"]
                for call in message.tool_calls
                if call.get("id")
            }

            break

    if last_call_index is None:
        return {}

    if not tool_call_ids:
        return {}

    updates = {}

    for message in messages[
        last_call_index + 1:
    ]:

        if not isinstance(
            message,
            ToolMessage,
        ):
            continue

        if (
            message.tool_call_id
            not in tool_call_ids
        ):
            continue

        if not isinstance(
            message.content,
            str,
        ):
            continue

        try:
            data = json.loads(
                message.content
            )

        except json.JSONDecodeError:
            continue

        if not isinstance(
            data,
            dict,
        ):
            continue

        if data.get("success") is not True:
            continue

        if (
            data.get("result_type")
            != "incident_history"
        ):
            continue

        result_device_id = data.get(
            "device_id"
        )

        if (
            result_device_id
            and result_device_id.upper()
            != current_device_id
        ):
            continue

        records = data.get(
            "records",
            [],
        )

        if not isinstance(
            records,
            list,
        ):
            continue

        valid_incident_ids = []

        for record in records:

            if not isinstance(
                record,
                dict,
            ):
                continue

            incident = record.get(
                "incident"
            )

            if not isinstance(
                incident,
                dict,
            ):
                continue

            if (
                incident.get("device_id")
                != current_device_id
            ):
                continue

            incident_id = incident.get(
                "incident_id"
            )

            if (
                isinstance(
                    incident_id,
                    str,
                )
                and incident_id
            ):
                valid_incident_ids.append(
                    incident_id
                )

        unique_ids = list(
            dict.fromkeys(
                valid_incident_ids
            )
        )

        previous_incident_id = state.get(
            "current_incident_id"
        )

        if len(unique_ids) == 1:
            updates[
                "current_incident_id"
            ] = unique_ids[0]

        elif previous_incident_id in unique_ids:
            updates[
                "current_incident_id"
            ] = previous_incident_id

        else:
            updates[
                "current_incident_id"
            ] = None

    return updates


# ============================================================
# 7. 构建只读 Chat Graph
# ============================================================

builder = StateGraph(
    ChatState
)

builder.add_node(
    "prepare_chat",
    prepare_chat_node,
)

builder.add_node(
    "chat_agent",
    chat_agent_node,
)

builder.add_node(
    "tools",
    timed_tools_node,
)

builder.add_node(
    "sync_business_memory",
    sync_business_memory_node,
)


builder.add_edge(
    START,
    "prepare_chat",
)

builder.add_edge(
    "prepare_chat",
    "chat_agent",
)

builder.add_conditional_edges(
    "chat_agent",
    tools_condition,
)

builder.add_edge(
    "tools",
    "sync_business_memory",
)

builder.add_edge(
    "sync_business_memory",
    "chat_agent",
)


# ============================================================
# 8. SQLite Checkpointer
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CHECKPOINT_DB = (
    PROJECT_ROOT
    / "data"
    / "chat_checkpoints.db"
)

CHECKPOINT_DB.parent.mkdir(
    parents=True,
    exist_ok=True,
)

checkpoint_connection = sqlite3.connect(
    CHECKPOINT_DB,
    check_same_thread=False,
)

checkpointer = SqliteSaver(
    checkpoint_connection
)

chat_graph = builder.compile(
    checkpointer=checkpointer,
)
