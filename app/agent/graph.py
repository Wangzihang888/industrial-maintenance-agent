# ============================================================
# Graph Definition
# ============================================================


# ============================================================
# Imports
# ============================================================

from langgraph.graph import (
    StateGraph,
    START,
    END,
)


import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


from langgraph.prebuilt import (
    ToolNode,
    tools_condition,
)



from app.state import AgentState


# ============================================================
# Nodes
# ============================================================

from app.nodes.agent_node import (
    agent_node,
)


from app.nodes.extract_node import (
    extract_tool_results_node,
)


from app.nodes.evaluate_node import (
    evaluate_temperature_node,
    decide_action_node,
)


from app.nodes.notification_node import (
    notification_node,
)


from app.nodes.ticket_node import (
    ticket_request_node,
    create_ticket_node,
)


from app.nodes.approval_node import (
    approval_node,
)



# ============================================================
# Routers
# ============================================================

from app.routers.extract_router import (
    route_after_extract,
)


from app.routers.action_router import (
    route_after_decision,
)


from app.routers.approval_router import (
    route_after_approval,
)
# ============================================================
# Tools
# ============================================================

from app.agent.llm import (
    query_tools,
)



# ============================================================
# 1. Tool Node
# ============================================================


tool_node = ToolNode(
    query_tools
)



# ============================================================
# 2. Create Graph
# ============================================================


builder = StateGraph(
    AgentState
)



# ============================================================
# 3. Register Nodes
# ============================================================


builder.add_node(
    "agent",
    agent_node,
)


builder.add_node(
    "tools",
    tool_node,
)


builder.add_node(
    "extract",
    extract_tool_results_node,
)


builder.add_node(
    "evaluate",
    evaluate_temperature_node,
)


builder.add_node(
    "decide_action",
    decide_action_node,
)


builder.add_node(
    "notification",
    notification_node,
)


builder.add_node(
    "ticket_request",
    ticket_request_node,
)


builder.add_node(
    "approval",
    approval_node,
)


builder.add_node(
    "create_ticket",
    create_ticket_node,
)



# ============================================================
# 4. Define Workflow
# ============================================================


# START → Agent

builder.add_edge(
    START,
    "agent",
)



# Agent → Tools / END

builder.add_conditional_edges(
    "agent",
    tools_condition,
)



# Tools → Extract

builder.add_edge(
    "tools",
    "extract",
)



# Extract → Evaluate / Agent

builder.add_conditional_edges(
    "extract",
    route_after_extract,
    {
        "evaluate":
            "evaluate",

        "agent":
            "agent",
    },
)



# ============================================================
# Evaluate → Decision
# ============================================================

builder.add_edge(
    "evaluate",
    "decide_action",
)


# ============================================================
# Decision → Action Branches
# ============================================================

builder.add_conditional_edges(
    "decide_action",
    route_after_decision,
    {
        "notification":
            "notification",

        "ticket_request":
            "ticket_request",

        "end":
            END,
    },
)


# ============================================================
# Notification → END
# ============================================================

builder.add_edge(
    "notification",
    END,
)


# ============================================================
# Ticket Request → Approval
# ============================================================

builder.add_edge(
    "ticket_request",
    "approval",
)


# ============================================================
# Approval → Create Ticket
# ============================================================

builder.add_conditional_edges(
    "approval",
    route_after_approval,
    {
        "create_ticket":
            "create_ticket",

        "end":
            END,
    },
)

# ============================================================
# Create Ticket → END
# ============================================================

builder.add_edge(
    "create_ticket",
    END,
)
# ============================================================
# 5. Compile
# ============================================================


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CHECKPOINT_DB = (
    PROJECT_ROOT / "data" / "langgraph_checkpoints.db"
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

graph = builder.compile(
    checkpointer=checkpointer,
)