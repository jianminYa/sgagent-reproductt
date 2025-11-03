"""Workflow graph construction for ISEA agent system"""
import functools
from typing import List, Any
from settings import settings
from langgraph.graph import END, StateGraph, START

from agent.state import AgentState
from agent.core import agent_node, custom_tool_node, create_agent
from router.router import (
    locator_router,
    suggester_router,
    fixer_router,
    summarize_router
)
from .summarizer import summarize
model_type = settings.openai_model

def create_workflow(
    llm,
    locator_tools: List[Any],
    suggester_tools: List[Any],
    fixer_tools: List[Any],
    locator_template,
    suggester_template,
    fixer_template,
    base_dir: str,
    project_name: str
):
    """Create the complete workflow graph"""

    # Create agents
    locator_agent = create_agent(
        llm, locator_tools, locator_template,
        base_dir + "/" + project_name, project_name
    )
    suggester_agent = create_agent(
        llm, suggester_tools, suggester_template,
        base_dir + "/" + project_name, project_name,
    )
    fixer_agent = create_agent(
        llm, fixer_tools, fixer_template,
        base_dir + "/" + project_name, project_name
    )

    # Create tool maps and nodes
    locator_tool_map = {tool.name: tool for tool in locator_tools}
    locator_tool_node = functools.partial(custom_tool_node, tool_map=locator_tool_map)

    suggester_tool_map = {tool.name: tool for tool in suggester_tools}
    suggester_tool_node = functools.partial(custom_tool_node, tool_map=suggester_tool_map)

    fixer_tool_map = {tool.name: tool for tool in fixer_tools}
    fixer_tool_node = functools.partial(custom_tool_node, tool_map=fixer_tool_map)

    # Create agent nodes
    locator_node = functools.partial(agent_node, agent=locator_agent, name="Locator", model_type=model_type)
    suggester_node = functools.partial(agent_node, agent=suggester_agent, name="Suggester", model_type=model_type)
    fixer_node = functools.partial(agent_node, agent=fixer_agent, name="Fixer", model_type=model_type)

    # Create summarizer with LLM
    summarize_node = functools.partial(summarize, llm=llm)

    # Build workflow graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("Locator", locator_node)
    workflow.add_node("Suggester", suggester_node)
    workflow.add_node("Fixer", fixer_node)
    workflow.add_node("locator_tool_node", locator_tool_node)
    workflow.add_node("suggester_tool_node", suggester_tool_node)
    workflow.add_node("fixer_tool_node", fixer_tool_node)
    workflow.add_node("summarize", summarize_node)

    # Add edges
    workflow.add_edge(START, "Locator")
    workflow.add_edge("locator_tool_node", "Locator")
    workflow.add_edge("suggester_tool_node", "Suggester")
    workflow.add_edge("fixer_tool_node", "Fixer")

    # Add conditional edges
    workflow.add_conditional_edges(
        "Locator",
        locator_router,
        {
            "continue": "Locator",
            "suggester": "Suggester",
            "call_tool": "locator_tool_node",
            "summarize": "summarize",
        },
    )

    workflow.add_conditional_edges(
        "Suggester",
        suggester_router,
        {
            "continue": "Suggester",
            "fixer": "Fixer",
            "locator": "Locator",
            "call_tool": "suggester_tool_node",
            "summarize": "summarize",
        },
    )

    workflow.add_conditional_edges(
        "Fixer",
        fixer_router,
        {
            "Fixer": "Fixer",
            "Locator": "Locator",
            "Suggester": "Suggester",
            "call_tool": "fixer_tool_node",
            "summarize": "summarize",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "summarize",
        summarize_router,
        {"Fixer": "Fixer", "Locator": "Locator", "Suggester": "Suggester", "END": END},
    )

    return workflow