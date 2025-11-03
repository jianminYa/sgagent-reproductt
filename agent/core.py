"""Core agent functionality"""

import json
import re
import uuid
import subprocess
import os
from settings import settings
from agent.state import AgentState
from prompt import ANALYZE_PROMPT
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import (
    HumanMessage,
    ToolMessage,
    AIMessage,
)
from router.router import is_tool_result_message
from langchain_openai import ChatOpenAI
from collections import defaultdict
from pydantic import BaseModel, Field
from utils import record_api_call, process_patch
from pathlib import Path
from utils.logger import Logger

INSTANCE_ID = settings.INSTANCE_ID
PROJECT_NAME = settings.PROJECT_NAME
TEST_BED = settings.TEST_BED
PROBLEM_STATEMENT = settings.PROBLEM_STATEMENT
ROUND = settings.ROUND
model_type = settings.openai_model
res_json = {"location": [], "failed_patch": []}
logs_dir = Path(__file__).parent.parent / "logs"
timestamp = settings.timestamp
res_dir = logs_dir / ROUND / f"{INSTANCE_ID}_{timestamp}.json"

# Create logger instance for agent module
agent_logger = Logger(logs_dir / ROUND, f"{INSTANCE_ID}_{timestamp}.log")


class Location(BaseModel):
    file_path: str = Field(description="File path of your location")
    start_line: int = Field(description="Start line of your location")
    end_line: int = Field(description="End line of your location")


class Locations(BaseModel):
    locations: list[Location] = Field(
        description="A list of suspicious locations, should contain at most 5 entries"
    )


parser = PydanticOutputParser(pydantic_object=Locations)


def create_agent(
    llm, tools, prompt: ChatPromptTemplate, base_dir: str, project_name: str
):
    """Create an agent."""
    prompt = prompt.partial(base_dir=base_dir)
    return prompt | llm


# TODO @<hanyu> 手动
zero_llm = ChatOpenAI(
    model=model_type,
    temperature=0.8,
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    extra_body={"enable_thinking": False},
)
eighty_llm = ChatOpenAI(
    model=model_type,
    temperature=0.8,
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    extra_body={"enable_thinking": False},
)


def agent_node(state: AgentState, agent, name, model_type):
    # logger.log("info", "\n" + "="*30 + " current state['messages'] " + "="*30)
    # logger.log("info","\n[Summary]\n"+f"{state['summary']} \n")
    # logger.log("info", pformat(state["messages"]))
    # logger.log("info", "="*80 + "\n")
    # locator_router -> summarize :pass
    if len(state["messages"]) > 16 and (
        is_tool_result_message(state["messages"][-1])
        or isinstance(state["messages"][-1], HumanMessage)
        or (
            isinstance(state["messages"][-1], AIMessage)
            and "#TOOL_CALL" not in state["messages"][-1].content
        )
    ):
        print("⚠️ : [NEED TO SUMMARIZE]")
        return {"messages": []}
    if is_tool_result_message(state["messages"][-1]) and name != "Fixer":
        state["messages"] = state["messages"] + [HumanMessage(content=ANALYZE_PROMPT)]

    # Only add problem statement if not already in recent messages (avoid duplication)
    recent_has_problem_statement = any(
        isinstance(msg, HumanMessage) and "The problem statement the project is:" in str(msg.content)
        for msg in state["messages"][-5:] if hasattr(msg, 'content')
    )
    if not recent_has_problem_statement:
        state["messages"] = state["messages"] + [
            HumanMessage(
                content=f"The problem statement the project is:\n{state['problem_statement']}"
            )
        ]
    if name == "Fixer":
        for idx, loc in enumerate(state["locations"]):
            with open(loc["file_path"], "r", encoding="utf-8") as file:
                lines = file.readlines()

            content = "".join(lines[loc["start_line"] - 1 : loc["end_line"]])
            location_label = f"[Location {idx + 1}] {loc['file_path']} lines {loc['start_line']}-{loc['end_line']}"

            location = HumanMessage(
                content=(
                    f"Bug Locations\n:"
                    f"{location_label}\n"
                    f"{'-' * len(location_label)}\n"
                    f"{content}\n\n"
                )
            )
            state["messages"] = state["messages"] + [location]

    if name == "Fixer":
        state["messages"] = state["messages"] + [
            HumanMessage(
                content="**Observe the leading whitespace of the content above** and indent your patch to match its context; do not always produce flush-left code.\n"
            )
        ]
    # AI: info enough  Human : []  AI : propose location  Human :[prompt] AI: json {}
    if state.get("ready_to_locate", False):
        state["messages"] += [
            HumanMessage(
                content=(
                    "Now, please provide at most 5 suspicious locations at once and output them in the format of a JSON list. It must follow the following structure:  example:\n"
                    """
```json
{
    "locations": [
        {
            "file_path": "/root/hy/projects/sphinx/sphinx/ext/viewcode.py",
            "start_line": 181,
            "end_line": 276
        },
        {
            "file_path": "/root/hy/projects/sphinx/sphinx/ext/viewcode.py",
            "start_line": 160,
            "end_line": 178
        }
    ]
}
```
                """
                )
            )
        ]

    # summarize:pass
    summary = state.get("summary", "")
    locations = state.get("locations", [])
    if locations:
        location_info_parts = []
        for location in locations:
            path = location.get("file_path", "")
            start_line = location.get("start_line", "")
            end_line = location.get("end_line", "")
            location_info = (
                f"Suspicious location by the Locator:\n"
                f"Path: {path}\n"
                f"Start line: {start_line}\n"
                f"End line: {end_line}\n"
            )
            location_info_parts.append(location_info)
        location_info = "\n".join(location_info_parts) if location_info_parts else ""
        summary = summary + ("\n" + location_info if summary else location_info)
    if state["suggestion"] != "":
        summary = (
            summary + "\nCurrent suggestions by the suggester:\n" + state["suggestion"]
        )
    if name == "Fixer":
        summary = (
            summary
            + "\nNote that the Patch provided should be a direct substitution of the location code by the Locator."
        )
    if summary:
        human_message = f"Summary of conversation earlier: {summary}"
        messages = [HumanMessage(content=human_message)] + state["messages"]
    else:
        messages = state["messages"]

    state["messages"] = messages

    # Add detailed error handling for API calls
    try:
        result = agent.invoke(state)
    except Exception as api_error:
        import traceback
        error_details = traceback.format_exc()
        agent_logger.error("=" * 80)
        agent_logger.error(f"⚠️ API CALL FAILED - Agent: {name}")
        agent_logger.error("=" * 80)
        agent_logger.error(f"Error Type: {type(api_error).__name__}")
        agent_logger.error(f"Error Message: {str(api_error)}")
        agent_logger.error("-" * 80)
        agent_logger.error("Full Traceback:")
        agent_logger.error(error_details)
        agent_logger.error("=" * 80)
        raise  # Re-raise the exception after logging


    try:
        prompt_content = "\n".join(
            [str(msg.content) for msg in state["messages"] if hasattr(msg, "content")]
        )

        response_content = str(result)
        if hasattr(result, "content"):
            response_content = result.content

        prompt_tokens = None
        completion_tokens = None
        if hasattr(result, "response_metadata"):
            usage = result.response_metadata.get("token_usage", {})
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")

        record_api_call(
            model_type,
            prompt_content,
            response_content,
            prompt_tokens,
            completion_tokens,
        )
    except Exception as e:
        print(f"Failed to record API call stats: {e}")

    content = ""
    state["update_num"] = 1
    if isinstance(result, ToolMessage):
        res = [result]
    else:
        result = AIMessage(**result.model_dump(exclude={"type", "name"}), name=name)
        res = [result]

        # location parsed: pass
        if state.get("ready_to_locate", False) and name == "Locator":
            try:
                # Parse the JSON output into Location objects using Pydantic parser
                locs = parser.parse(result.content).locations
                # Store parsed locations in state as list of dicts
                state["locations"] = [
                    {
                        "file_path": loc.file_path,
                        "start_line": loc.start_line,
                        "end_line": loc.end_line,
                    }
                    for loc in locs
                ]
                # Set primary location for backward compatibility
                state["location"] = state["locations"][0]

                # Populate res_json with each location's content snippet
                for loc in locs:
                    with open(loc.file_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    content = "".join(lines[loc.start_line - 1 : loc.end_line])
                    res_json.setdefault("location", []).append(
                        {
                            "file_path": loc.file_path,
                            "start_line": loc.start_line,
                            "end_line": loc.end_line,
                            "content": content,
                        }
                    )

            except Exception as e:
                # JSON parsing failed: prompt the model to re-output valid JSON schema
                agent_logger.error("=" * 80)
                agent_logger.error("⚠️ JSON PARSING FAILED - DEBUG INFO:")
                agent_logger.error("=" * 80)
                agent_logger.error(f"Exception: {type(e).__name__}: {str(e)}")
                agent_logger.error("-" * 80)
                agent_logger.error("AI Response Content:")
                agent_logger.error("-" * 80)
                agent_logger.error(result.content)
                agent_logger.error("=" * 80)

                # 🔧 SOLUTION 1: Check if Agent is trying to call a tool (indicated by #TOOL_CALL)
                if "#TOOL_CALL" in result.content:
                    # Agent wants to explore first - allow it!
                    # Don't replace the message, just keep ready_to_locate True
                    # and let the tool call execute normally
                    agent_logger.info("✓ Agent wants to explore before providing JSON - allowing tool call")
                    state["ready_to_locate"] = True  # Keep state for later
                    # Don't modify res - let the original AIMessage with tool call through
                    # The tool will be executed in the next step, and after that,
                    # Agent will have the information needed to provide valid JSON
                else:
                    # Agent provided invalid JSON without tool call - give feedback
                    # Check if this is a file not found error
                    is_file_not_found = isinstance(e, FileNotFoundError)

                    if is_file_not_found:
                        # Extract the problematic file path from the error
                        error_msg = str(e)
                        err = (
                            f"⚠️ ERROR: One or more file paths in your JSON do not exist.\n\n"
                            f"Details: {error_msg}\n\n"
                            "**IMPORTANT**: You must provide ABSOLUTE file paths that actually exist in the project.\n\n"
                            "**DO NOT GUESS file paths!** Instead:\n"
                            "1. Use #TOOL_CALL explore_directory or #TOOL_CALL search_code_with_context to find the correct files\n"
                            "2. Verify the exact absolute paths before outputting JSON\n"
                            "3. Ensure all paths start with the project root (e.g., /Users/hanyu/projects_2/django/...)\n\n"
                            "Please search for the correct file locations first, then provide valid JSON with VERIFIED absolute paths."
                        )
                    else:
                        # Generic JSON error
                        err = (
                            f"⚠️ JSON parsing failed: {type(e).__name__}: {str(e)}\n\n"
                            "Please output exactly a JSON object following this schema:\n"
                            + """
```json
{
    "locations": [
        {
            "file_path": "/absolute/path/to/file.py",
            "start_line": 181,
            "end_line": 276
        }
    ]
}
```
"""
                            + "\nEnsure:\n"
                            "- All file_path values are ABSOLUTE paths\n"
                            "- All files actually exist in the project\n"
                            "- start_line and end_line are valid integers"
                        )

                    res = [HumanMessage(content=err)]
                    # Keep ready_to_locate True to allow retry
                    state["ready_to_locate"] = True
                    state["update_num"] = 2
            else:
                # Successfully parsed locations
                state["ready_to_locate"] = False
                if state.get("next") == "Locator":
                    state["next"] = "Suggester"

        ## to be continued
        if (
            "INFO ENOUGH" in result.content
            and "PROPOSE LOCATION" not in result.content
            and name == "Locator"
            and "#TOOL_CALL" not in result.content
        ):
            res.append(
                HumanMessage(
                    content="If you think current information is enough to understand the root cause of the bug, add 'PROPOSE LOCATION' in your response to propose your location."
                )
            )
            state["ready_to_locate"] = True
            state["update_num"] = 2
        if (
            "INFO ENOUGH" in result.content
            and "PROPOSE SUGGESTION" not in result.content
            and name == "Suggester"
            and "#TOOL_CALL" not in result.content
        ):
            res.append(
                HumanMessage(
                    content="If you find things to explore or focus, then go for more information. If you think current information is enough to understand the root cause of the bug, add 'PROPOSE SUGGESTION' and your suggestion after that in your response."
                )
            )
            state["update_num"] = 2

        if (
            "PROPOSE SUGGESTION" in result.content
            and name == "Suggester"
            and "#TOOL_CALL" not in result.content
        ):
            state["suggestion"] = result.content.replace("PROPOSE SUGGESTION", "")
            location_segments = []
            for idx, loc in enumerate(state["locations"]):
                with open(loc["file_path"], "r") as file:
                    content = "".join(
                        file.readlines()[loc["start_line"] - 1 : loc["end_line"]]
                    )
                location_label = f"[Location {idx + 1}] {loc['file_path']} lines {loc['start_line']}-{loc['end_line']}"
                location_segments.append(
                    f"{location_label}\n{'-' * len(location_label)}\n{content}"
                )

            question = HumanMessage(
                content=(
                    "According to the suggestions provided earlier, please review the following code segments:\n\n"
                    + "\n\n".join(location_segments)
                    + "\n\n"
                    "Based on the suggestion, do you think these locations are ready for fixing?\n"
                    "If yes, please respond with '**CONTINUE TO FIX**' and then you will switch to Fixer state, proceed to implement the fix later.\n"
                    "If not, explain why and state that further clarification is needed."
                )
            )
            res.append(question)
            state["update_num"] = 2

        if "CONTINUE TO FIX" in result.content and "#TOOL_CALL" not in result.content:
            location_contents = []

            for idx, loc in enumerate(state["locations"]):
                # Read the full file so we can extract imports + snippet
                with open(loc["file_path"], "r", encoding="utf-8") as file:
                    lines = file.readlines()

                # Extract 3 lines before and after the vulnerability location
                start_context = max(0, loc["start_line"] - 11)
                end_context = min(len(lines), loc["end_line"] + 10)

                context_lines = []
                for line_num in range(start_context, end_context):
                    line = lines[line_num].rstrip()
                    if loc["start_line"] - 1 <= line_num < loc["end_line"]:
                        # Vulnerability lines - keep original format
                        context_lines.append(f"[R] {line_num + 1:4d}: {line}")
                    else:
                        # Context lines - mark with [C]
                        context_lines.append(f"[C] {line_num + 1:4d}: {line}")

                content = "\n".join(context_lines)

                imports = [
                    line.strip()
                    for line in lines
                    if line.strip().startswith("import ")
                    or line.strip().startswith("from ")
                ]

                # Build a label for this location
                location_label = f"[Location {idx + 1}] {loc['file_path']} lines {loc['start_line']}-{loc['end_line']}"

                # Compose the location content
                location_content = (
                    f"{location_label}\n\n"
                    f"Imports in this file: You can select the functions that may be needed to assist with the repair.\n"
                    + "\n".join(f"  {imp}" for imp in imports)
                    + "\n\n"
                    "When generating patches, **do NOT add duplicate imports** that already exist in the above list.\n\n"
                    f"The following is the code content with context ([R] marks vulnerability lines, [C] marks context lines):\n"
                    f"{'-' * len(location_label)}\n"
                    f"{content}\n\n"
                )
                location_contents.append(location_content)

            # Create a single HumanMessage with all location contents and instructions
            combined_content = (
                "\n".join(location_contents)
                + "You must pay close attention to **indentation** — especially the relative indentation level between the patch and its parent scope (for example, the containing class or function).\n"
                "⚠️ **Observe the leading whitespace of the content above** and indent your patch to match its context; do not always produce flush-left code.\n"
                "⚠️ **Do not combine fixes for different locations into one block** — every location's fix should be in a **separate** ```python```code block.\n\n"
                f"Here are the suggestions from the Suggester:\n{state['suggestion']}\n\n"
                "You may search or reference other code if necessary.\n\n"
                "**When you're ready, start your reply with '#PROPOSE PATCH' and then include all  code blocks.**"
                """
#PROPOSE PATCH
```python
<patch_1>
```
```python
<patch_2>
```
...
"""
            )
            message = HumanMessage(content=combined_content)
            res.append(message)
            state["next"] = "Fixer"
            state["suggest_count"] += 1
            state["update_num"] = 2

        if "PROPOSE PATCH" in result.content:
            state["fix_count"] += 1

            labels = []
            zero_patches = {}
            variant_patches = {}

            raw_blocks = re.findall(r"```python(.*?)```", result.content, re.DOTALL)
            n_pre = min(len(raw_blocks), len(state["locations"]))

            repo_root = Path(TEST_BED) / PROJECT_NAME

            for idx, loc in enumerate(state["locations"]):
                pre_patch = raw_blocks[idx] if idx < n_pre else None
                print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
                print(pre_patch)
                print(type(pre_patch))
                print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")

                pre_patch = process_patch(
                    str(pre_patch), loc["file_path"], loc["start_line"]
                )

                # Read the full file to extract imports and context
                with open(loc["file_path"], "r", encoding="utf-8") as file:
                    lines = file.readlines()

                # Extract 3 lines before and after the vulnerability location for context
                start_context = max(0, loc["start_line"] - 11)
                end_context = min(len(lines), loc["end_line"] + 10)

                context_lines = []
                for line_num in range(start_context, end_context):
                    line = lines[line_num].rstrip()
                    if loc["start_line"] - 1 <= line_num < loc["end_line"]:
                        context_lines.append(f"[R] {line_num + 1:4d}: {line}")
                    else:
                        context_lines.append(f"[C] {line_num + 1:4d}: {line}")

                context_content = "\n".join(context_lines)

                # Extract imports from the file
                imports = [
                    line.strip()
                    for line in lines
                    if line.strip().startswith("import ")
                    or line.strip().startswith("from ")
                ]

                label = (
                    f"Location {idx + 1} "
                    f"({loc['file_path']} lines {loc['start_line']}-{loc['end_line']})"
                )
                labels.append(label)

                # Create comprehensive prompt with context and imports
                imports_text = "\n".join(f"  {imp}" for imp in imports)
                prompt = [
                    HumanMessage(
                        content=(
                            f"{label}\n\n"
                            f"Available imports in this file:\n{imports_text}\n\n"
                            f"Code context ([R] marks vulnerability lines, [C] marks context lines):\n"
                            f"{context_content}\n\n"
                            f"Suggestions from analysis:\n{state['suggestion']}\n\n"
                            "Instructions:\n"
                            "- Please propose a complete, corrected Python code snippet to fix this location\n"
                            "- Pay attention to indentation and match the surrounding context\n"
                            "- Do NOT add duplicate imports that already exist above\n"
                            "- Wrap your code in a ```python ``` block\n"
                            "- Output only the corrected code without additional explanations"
                        )
                    )
                ]

                resp0 = zero_llm.invoke(prompt)
                # 记录API调用统计
                try:
                    # 提取提示内容
                    prompt_content = ""
                    if isinstance(prompt, list):
                        prompt_content = "\n".join(
                            [
                                str(msg.content)
                                for msg in prompt
                                if hasattr(msg, "content")
                            ]
                        )
                    else:
                        prompt_content = str(prompt)

                    # 提取响应内容
                    response_content = str(resp0)
                    if hasattr(resp0, "content"):
                        response_content = resp0.content

                    # 尝试获取token信息
                    prompt_tokens = None
                    completion_tokens = None
                    if hasattr(resp0, "response_metadata"):
                        usage = resp0.response_metadata.get("token_usage", {})
                        prompt_tokens = usage.get("prompt_tokens")
                        completion_tokens = usage.get("completion_tokens")

                    record_api_call(
                        model_type,
                        prompt_content,
                        response_content,
                        prompt_tokens,
                        completion_tokens,
                    )
                except Exception as e:
                    print(f"Failed to record API call stats: {e}")

                code0 = re.search(r"```python(.*?)```", resp0.content, re.DOTALL).group(
                    1
                )
                zero_patches[label] = code0

                variants = []
                for _ in range(8):
                    resp = eighty_llm.invoke(prompt)

                    try:
                        prompt_content = ""
                        if isinstance(prompt, list):
                            prompt_content = "\n".join(
                                [
                                    str(msg.content)
                                    for msg in prompt
                                    if hasattr(msg, "content")
                                ]
                            )
                        else:
                            prompt_content = str(prompt)

                        response_content = str(resp)
                        if hasattr(resp, "content"):
                            response_content = resp.content

                        prompt_tokens = None
                        completion_tokens = None
                        if hasattr(resp, "response_metadata"):
                            usage = resp.response_metadata.get("token_usage", {})
                            prompt_tokens = usage.get("prompt_tokens")
                            completion_tokens = usage.get("completion_tokens")

                        record_api_call(
                            model_type,
                            prompt_content,
                            response_content,
                            prompt_tokens,
                            completion_tokens,
                        )
                    except Exception as e:
                        print(f"Failed to record API call stats: {e}")

                    print("==================")
                    print(resp.content)
                    print("==================")

                    variant = re.search(
                        r"```python(.*?)```", resp.content, re.DOTALL
                    ).group(1)
                    variants.append(variant)
                variant_patches[label] = variants

            original_contents = {}
            for loc in state["locations"]:
                path = loc["file_path"]
                with open(path, "r", encoding="utf-8") as f:
                    original_contents[path] = f.read()

            def apply_and_diff(patches_dict):
                original_contents = {}
                for loc in state["locations"]:
                    path = loc["file_path"]
                    with open(path, "r", encoding="utf-8") as f:
                        original_contents[path] = f.read()
                labels = []

                for idx, loc in enumerate(state["locations"]):
                    label = (
                        f"Location {idx + 1} "
                        f"({loc['file_path']} lines {loc['start_line']}-{loc['end_line']})"
                    )
                    labels.append(label)
                file_edits = defaultdict(list)
                for label, code in patches_dict.items():
                    idx = labels.index(label)
                    loc = state["locations"][idx]
                    path = loc["file_path"]
                    file_edits[path].append(
                        (loc["start_line"] - 1, loc["end_line"], code.splitlines())
                    )

                for path, edits in file_edits.items():
                    orig = original_contents[path].splitlines(keepends=True)

                    for start, end, new_lines in sorted(
                        edits, key=lambda x: x[0], reverse=True
                    ):
                        patched = (
                            orig[:start]
                            + [
                                l + "\n" if not l.endswith("\n") else l
                                for l in new_lines
                            ]
                            + orig[end:]
                        )
                        orig = patched

                    with open(path, "w", encoding="utf-8") as f:
                        f.writelines(orig)

                diff = subprocess.check_output(
                    ["git", "-C", str(repo_root), "diff"], stderr=subprocess.STDOUT
                ).decode("utf-8", errors="ignore")

                for path, content in original_contents.items():
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
                return diff

            pre_patches = {
                labels[i]: raw_blocks[i] if i < n_pre else ""
                for i in range(len(labels))
            }
            diffs_by_variant = {
                "raw_patch": apply_and_diff(pre_patches),
                "variant_0": apply_and_diff(zero_patches),
            }

            num_variants = len(next(iter(variant_patches.values())))
            for i in range(num_variants):
                one_variant = {label: variant_patches[label][i] for label in labels}
                diffs_by_variant[f"variant_{i + 1}"] = apply_and_diff(one_variant)

            try:
                os.makedirs(os.path.dirname(res_dir), exist_ok=True)
                with open(res_dir, "w", encoding="utf-8") as out_f:
                    json.dump(
                        {
                            "zero_patches": zero_patches,
                            "variant_patches": variant_patches,
                            "combined_diffs": diffs_by_variant,
                        },
                        out_f,
                        indent=2,
                        ensure_ascii=False,
                    )
                print(f"✅ Exported combined patches and multi-file diffs to {res_dir}")
            except Exception as e:
                print(f"❌ Failed to write patches JSON: {e}")

            state["update_num"] = 2
            state["next"] = "END"

        if (
            name == "Fixer"
            and "PROPOSE PATCH" not in result.content
            and result.content.strip()
            and "#TOOL_CALL" not in result.content
        ):
            # Prompt user to include the PROPOSE PATCH marker and Python code block
            for i, loc in enumerate(state["locations"]):
                with open(loc["file_path"], "r") as file:
                    lines = file.readlines()
                code_snippet = "".join(lines[loc["start_line"] - 1 : loc["end_line"]])
                res.append(
                    HumanMessage(
                        content=(
                            f"[Location {i + 1}] {loc['file_path']} lines {loc['start_line']}-{loc['end_line']}\n\n"
                            f"The code to be fixed is:\n{code_snippet}\n\n"
                        )
                    )
                )
            res.append(
                HumanMessage(
                    content=(
                        "⚠️ Please begin your response with **#PROPOSE PATCH**, \n"
                        """
                - Output exactly one code block wrapped in triple backticks with the language tag python (i.e., ```python ... ```).
                - The number of code blocks you output must exactly match the number of provided locations, and must appear in the same order.
                - Each code block will overwrite the corresponding location in the original file.
                - Therefore, if you believe a specific location does not need to be changed, you must still output the original, unmodified code for that location.

                Do not skip any location. Do not combine multiple locations in one block. Always output one python code block per location.
                """
                    )
                )
            )
            state["update_num"] = 2
    return {
        "messages": res,
        "location": state["location"],
        "locations": state["locations"],
        "suggestion": state["suggestion"],
        "suggest_count": state["suggest_count"],
        "fix_count": state["fix_count"],
        "patch": state["patch"],
        "ready_to_locate": state["ready_to_locate"],
        "ready_to_fix": state["ready_to_fix"],
        "summary": state["summary"],
        "invoker": name,
        "next": state["next"],
        "failed_location": state["failed_location"],
        "update_num": state["update_num"],
        "location_content": state["location_content"],
        "problem_statement": state["problem_statement"],
    }


def parse_all_tool_calls(content: str):
    """Parse tool calls from content"""
    matches = re.findall(r"#TOOL_CALL\s+(\w+)\s+({.*?})", content, re.DOTALL)
    results = []
    for tool_name, arg_str in matches:
        try:
            args = json.loads(arg_str)
        except json.JSONDecodeError:
            args = {}
        results.append((tool_name, args))
    return results


def custom_tool_node(state: AgentState, tool_map: dict):
    """Execute custom tools based on tool calls in messages"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return state

    tool_calls = parse_all_tool_calls(last_message.content)
    if not tool_calls:
        return state

    for tool_name, args in tool_calls:
        if tool_name not in tool_map:
            continue

        call_id = uuid.uuid4().hex[:8]
        tool_fn = tool_map[tool_name]

        try:
            result = (
                tool_fn.invoke(args) if hasattr(tool_fn, "invoke") else tool_fn(**args)
            )
        except Exception as e:
            result = f"[❌ Tool execution error: {e}]"

        state["messages"].append(HumanMessage(content=f"/\/ Tool Result:\n{result}"))

    return state
