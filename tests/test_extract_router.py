
import json

from langchain_core.messages import ToolMessage

from app.routers.extract_router import route_after_extract


def main():

    # 自动 E-101：有设备状态和 RAG 返回，无温度历史
    e101_state = {
        "execution_mode": "automatic",
        "device_status": {
            "device_id": "RB-001",
            "temperature": 53.0,
            "current_alarm": "E-101",
        },
        "messages": [
            ToolMessage(
                content=json.dumps({
                    "result_type": "fault_knowledge",
                    "knowledge": "编码器通信异常排查资料",
                }),
                tool_call_id="test-rag-101",
            )
        ],
    }

    assert route_after_extract(e101_state) == "evaluate"

    print("通过：E-101 不需要温度历史即可进入评估")

    # 自动 E-102：有设备状态和 RAG 返回，无温度历史
    e102_state = {
        **e101_state,
        "device_status": {
            "device_id": "RB-002",
            "current_alarm": "E-102",
        },
    }

    assert route_after_extract(e102_state) == "evaluate"

    print("通过：E-102 不需要温度历史即可进入评估")

    # 知识库没有证据，但已返回结果
    no_evidence_state = {
        **e101_state,
        "messages": [
            ToolMessage(
                content=json.dumps({
                    "result_type": "fault_knowledge",
                    "knowledge": None,
                }),
                tool_call_id="test-rag-empty",
            )
        ],
    }

    assert route_after_extract(no_evidence_state) == "evaluate"

    print("通过：RAG 无证据时不会因空结果循环")

    # 自动任务缺少 RAG 返回
    missing_rag_state = {
        "execution_mode": "automatic",
        "device_status": {"device_id": "RB-001"},
        "messages": [],
    }

    assert route_after_extract(missing_rag_state) == "agent"

    print("通过：尚未调用 RAG 时返回 Agent")

    # 原有人工温度查询行为
    manual_state = {
        "execution_mode": "manual",
        "device_status": {"device_id": "RB-003"},
        "temperature_records": [],
        "messages": [],
    }

    assert route_after_extract(manual_state) == "evaluate"

    print("通过：原有人工温度查询逻辑保持兼容")

    print("\nExtract Router 测试全部通过！")


if __name__ == "__main__":
    main()
