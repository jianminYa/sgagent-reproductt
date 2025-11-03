"""
Router functions for agent workflow
"""

from langchain_core.messages import HumanMessage,AIMessage

from agent.state import AgentState


def is_tool_result_message(message):
    """Check if message is a tool result message"""
    return isinstance(message, HumanMessage) and message.content.startswith(
        "/\/ Tool Result:"
    )


def locator_router(state: "AgentState"):
    """Router for locator agent"""

    messages = state["messages"]
    last_message = messages[-1]

    if len(messages) > 16 and (
        is_tool_result_message(last_message)
        or isinstance(last_message, HumanMessage)
        or (
            isinstance(last_message, AIMessage)
            and "#TOOL_CALL" not in last_message.content
        )
    ):
        return "summarize"

    if isinstance(last_message, AIMessage) and "#TOOL_CALL" in last_message.content:
        return "call_tool"

    if state.get("next") == "Suggester":
        return "suggester"

    return "continue"


def suggester_router(state: "AgentState"):
    """Router for suggester agent"""

    messages = state["messages"]
    last_message = messages[-1]

    if len(messages) > 16 and (
        is_tool_result_message(last_message)
        or isinstance(last_message, HumanMessage)
        or (
            isinstance(last_message, AIMessage)
            and "#TOOL_CALL" not in last_message.content
        )
    ):
        return "summarize"

    if isinstance(last_message, AIMessage) and "#TOOL_CALL" in last_message.content:
        return "call_tool"

    if state.get("next") == "Fixer":
        return "fixer"
    if state.get("next") == "Locator":
        return "locator"

    return "continue"


def fixer_router(state: "AgentState"):
    """Router for fixer agent"""

    messages = state["messages"]
    last_message = messages[-1]

    if len(messages) > 16 and (
        is_tool_result_message(last_message)
        or isinstance(last_message, HumanMessage)
        or (
            isinstance(last_message, AIMessage)
            and "#TOOL_CALL" not in last_message.content
        )
    ):
        return "summarize"

    if isinstance(last_message, AIMessage) and "#TOOL_CALL" in last_message.content:
        return "call_tool"

    if state.get("next") == "END":
        # Note: logger functionality would need to be imported or passed in
        # logger.log("info", "Succeed!!")
        return "end"

    return state.get("next", "continue")


def summarize_router(state: "AgentState"):
    """Router for summarize node"""
    return state["next"]