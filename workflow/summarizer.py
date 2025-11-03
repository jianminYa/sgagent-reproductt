"""Summarization functionality for agent workflow"""
from typing import Dict, Any
from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage

from agent.state import AgentState
from router.router import is_tool_result_message
from utils.logging import record_api_call


def summarize(state: AgentState, llm) -> Dict[str, Any]:
    """Summarize conversation to manage context length"""
    replace_sum = True
    summary = state.get("summary", "")

    # Convert state["messages"] to text format
    messages_text = ""
    for i, msg in enumerate(state["messages"]):
        if isinstance(msg, HumanMessage):
            messages_text += f"User: {msg.content}\n\n"
        elif isinstance(msg, AIMessage):
            if msg.content:
                messages_text += f"Assistant: {msg.content}\n"
        elif isinstance(msg, HumanMessage):
            content = msg.content
            if content.startswith("// Tool Result:"):
                messages_text += f"Tool Result: {content[:500]}{'...' if len(content) > 500 else ''}\n\n"
            else:
                messages_text += f"{content[:1000]}{'...' if len(content) > 1000 else ''}\n\n"

    # Improved message length threshold judgment
    if summary and len(summary) > 2000:
        summary_message = (
            f"Previous conversation summary: {summary}\n\n"
            "Recent conversation messages:\n"
            f"{messages_text}\n"
            "Please create a comprehensive summary that:\n"
            "1. Retains all key information from the previous summary\n"
            "2. Incorporates important details from the new messages above\n"
            "3. Focuses on concrete actions taken, results achieved, and current status\n"
            "4. Highlights any errors, solutions, or important decisions made\n"
            "5. Maintains chronological context where relevant\n\n"
            "Your summary should be detailed enough to allow continuation of the task without losing important context."
        )
    elif summary and len(summary) <= 2000:
        replace_sum = False
        summary_message = (
            f"Current conversation summary: {summary}\n\n"
            "New conversation messages to add:\n"
            f"{messages_text}\n"
            "Please extend the existing summary by:\n"
            "1. Adding key information from the new messages above\n"
            "2. Maintaining the structure and context of the existing summary\n"
            "3. Highlighting any new progress, results, or important findings\n"
            "4. Preserving technical details and specific outcomes\n\n"
            "Add your extension to supplement the existing summary."
        )
    else:
        summary_message = (
            "Conversation messages to summarize:\n"
            f"{messages_text}\n"
            "Please create a comprehensive summary that includes:\n"
            "1. The main objectives and tasks being worked on\n"
            "2. Key actions taken and their results\n"
            "3. Any tools used and their outputs\n"
            "4. Current progress status and any issues encountered\n"
            "5. Important technical details or decisions made\n\n"
            "Focus on actionable information that would be needed to continue the work effectively."
        )

    # Only send summarization request, not including original messages
    messages = [HumanMessage(content=summary_message)]
    response = llm.invoke(messages)

    # Record API call statistics
    try:
        prompt_content = ""
        if isinstance(messages, list):
            prompt_content = "\n".join([str(msg.content) for msg in messages if hasattr(msg, 'content')])
        else:
            prompt_content = str(messages)

        response_content = str(response)
        if hasattr(response, 'content'):
            response_content = response.content

        prompt_tokens = None
        completion_tokens = None
        if hasattr(response, 'response_metadata'):
            usage = response.response_metadata.get('token_usage', {})
            prompt_tokens = usage.get('prompt_tokens')
            completion_tokens = usage.get('completion_tokens')

        record_api_call("summarizer", prompt_content, response_content, prompt_tokens, completion_tokens)
    except Exception as e:
        print(f"Failed to record API call stats: {e}")

    # Manage message history
    tool_call_id_dict = {}
    remaining_messages = []
    state["messages"] = state["messages"][1:]

    for message in reversed(state["messages"]):
        tool_call_id = []
        if isinstance(message, AIMessage):
            tool_call_list = message.additional_kwargs.get("tool_calls", [])
            tool_call_id = [elem.get("id") for elem in tool_call_list]
        if hasattr(message, 'tool_call_id'):
            tool_call_id = [message.tool_call_id]

        if len(remaining_messages) < 5 or is_tool_result_message(
            remaining_messages[-1] if remaining_messages else message
        ):
            remaining_messages.append(message)
            for idx in tool_call_id:
                if idx in tool_call_id_dict.keys():
                    tool_call_id_dict.pop(idx)
                else:
                    tool_call_id_dict[idx] = True
        if len(tool_call_id_dict) == 0 and len(remaining_messages) >= 4:
            break

    removed_list = [
        RemoveMessage(id=msg.id)
        for msg in [i for i in state["messages"] if i not in remaining_messages]
    ]

    return {
        "messages": removed_list,
        "summary": response.content
        if replace_sum
        else summary + "\n" + response.content,
    }