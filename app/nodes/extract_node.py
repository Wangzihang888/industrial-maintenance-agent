from app.state import AgentState
import json

from langchain_core.messages import ToolMessage

# ============================================================
# 5.3 Extract Tool Results Node
# ============================================================


def extract_tool_results_node(
    state: AgentState,
) -> dict:
    """
    将 ToolMessage 中的 JSON 结果，
    转换成 AgentState 字段。


    Tool:

    device_tool
        ↓
    device_status


    history_tool
        ↓
    temperature_records


    rag_tool
        ↓
    fault_knowledge
    """


    updates = {}


    for message in state.get(
        "messages",
        [],
    ):

        if not isinstance(
            message,
            ToolMessage,
        ):
            continue


        content = message.content


        if not isinstance(
            content,
            str,
        ):
            continue


        try:

            data = json.loads(
                content
            )


        except json.JSONDecodeError:

            continue



        if not isinstance(
            data,
            dict,
        ):

            continue



        result_type = data.get(
            "result_type"
        )


        # ----------------------------------------------------
        # Device Tool
        # ----------------------------------------------------

        if result_type == "device_status":

            device = data.get(
                "device"
            )

            if device:

                updates[
                    "device_status"
                ] = device



        # ----------------------------------------------------
        # History Tool
        # ----------------------------------------------------

        elif result_type == "temperature_history":

            records = data.get(
                "records"
            )

            if records is not None:

                updates[
                    "temperature_records"
                ] = records



        # ----------------------------------------------------
        # RAG Tool
        # ----------------------------------------------------

        elif result_type == "fault_knowledge":

            knowledge = data.get(
                "knowledge"
            )

            if knowledge:

                updates[
                    "fault_knowledge"
                ] = knowledge



    return updates