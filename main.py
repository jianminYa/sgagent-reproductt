import io
from datetime import datetime
from pathlib import Path
from contextlib import redirect_stdout
import pandas as pd
import os
from langgraph.errors import GraphRecursionError
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage


from prompt import locator_template, suggester_template, fixer_template
from workflow.graph import create_workflow
from router.router import is_tool_result_message
from script.reset import checkout_to_base_commit
from utils.logging import set_api_stats_file
from utils.logger import Logger
from settings import settings

def _get_problem_statement_by_instance_id(id):
    current_dir = Path(__file__).parent
    # parquet_path = current_dir / "dataset.parquet"
    parquet_path = current_dir /"dataset"/ "lite.parquet"

    df = pd.read_parquet(parquet_path)
    result = df.loc[df["instance_id"] == id, "problem_statement"]
    problem_statement = result.iloc[0] if not result.empty else None
    return problem_statement

# 检查是否禁用知识图谱
DISABLE_KG = os.environ.get('DISABLE_KG', '').lower() == 'true'
MODEL_TYPE = settings.openai_model or "claude-sonnet-4-20250514"
ROUND = settings.ROUND

# Use settings for project configuration
TEST_BED = settings.TEST_BED
PROJECT_NAME = settings.PROJECT_NAME
INSTANCE_ID = settings.INSTANCE_ID
PROBLEM_STATEMENT = _get_problem_statement_by_instance_id(INSTANCE_ID)

print("========ISEA Settings========")
print(f"{TEST_BED}")
print(f"{PROJECT_NAME}")
print(f"{INSTANCE_ID}")
print(f"DISABLE_KG: {DISABLE_KG}")
print("=============================")
# No external dependencies needed - using internal Logger
print("========================")
print(settings.openai_api_key)
print("========================")

llm = ChatOpenAI(
    model=MODEL_TYPE,
    temperature=0.0,
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    extra_body={"enable_thinking": False},
)

# Setup logging
base_dir = TEST_BED
project_name = PROJECT_NAME
timestamp = settings.timestamp
logs_dir = Path(__file__).parent / "logs"
logger = Logger(logs_dir / ROUND, f"{INSTANCE_ID}_{timestamp}.log")
api_stats_file = logs_dir / ROUND / f"{INSTANCE_ID}_{timestamp}_api_stats.json"
set_api_stats_file(str(api_stats_file))


def get_default_tools():
    """Get default tools"""
    # 一次性导入所有工具
    from tools.retriever_tools import (
        explore_directory,
        analyze_file_structure,
        find_files_containing,
        get_code_relationships,
        find_methods_by_name,
        extract_complete_method,
        find_class_constructor,
        list_class_attributes,
        show_file_imports,
        find_variable_usage,
        find_all_variables_named,
        read_file_lines,
        search_code_with_context,
        execute_shell_command_with_validation,
    )

    if DISABLE_KG:
        return [
            explore_directory,
            show_file_imports,
            read_file_lines,
            search_code_with_context,
            execute_shell_command_with_validation,
        ]
    else:
        return [
            explore_directory,
            analyze_file_structure,
            find_files_containing,
            get_code_relationships,
            find_methods_by_name,
            extract_complete_method,
            find_class_constructor,
            list_class_attributes,
            show_file_imports,
            find_variable_usage,
            find_all_variables_named,
            read_file_lines,
            search_code_with_context,
            execute_shell_command_with_validation,
        ]


def main():
    print("Starting ISEA")
    print("-" * 60)
    dir_name = Path(TEST_BED)/PROJECT_NAME
    checkout_to_base_commit(INSTANCE_ID, dir_name)

    # 不再需要 Neo4j 相关操作，知识图谱在 retriever_tools.py 中按需构建


    # Get tools
    locator_tools = get_default_tools()
    suggester_tools = get_default_tools()
    fixer_tools = get_default_tools()

    # Create workflow
    try:
        workflow = create_workflow(
            llm=llm,
            locator_tools=locator_tools,
            suggester_tools=suggester_tools,
            fixer_tools=fixer_tools,
            locator_template=locator_template,
            suggester_template=suggester_template,
            fixer_template=fixer_template,
            base_dir=base_dir,
            project_name=project_name,
        )

        graph = workflow.compile()
        print("Workflow created successfully")

    except Exception as e:
        print(f"Failed to create workflow: {e}")
        return

    # Initialize state
    initial_state = {
        "messages": [
            HumanMessage(content="Try to find and repair the bug in the project.")
        ],
        "initial_failure": None,
        "location": None,
        "locations": None,
        "suggestion": "",
        "suggest_count": 0,
        "fix_count": 0,
        "patch": "",
        "ready_to_locate": False,
        "ready_to_fix": False,
        "summary": "",
        "invoker": "",
        "next": "Locator",
        "failed_location": [],
        "update_num": 1,
        "location_content": "",
        "problem_statement": PROBLEM_STATEMENT,
    }

    # Run the workflow
    try:
        print("Starting workflow execution...")
        events = graph.stream(initial_state, {"recursion_limit": 150})

        for s in events:
            for a in s:
                # Special handling for summarize node
                if a == "summarize":
                    if "summary" in s[a]:
                        summary_text = s[a]["summary"]
                        logger.log("info", "=" * 32 + " Summarize " + "=" * 32)
                        logger.log("info", f"Summary: {summary_text[:500]}..." if len(summary_text) > 500 else f"Summary: {summary_text}")
                        logger.log("info", "=" * 80 + "\n")
                    continue

                if "messages" in s[a].keys():
                    results = ""
                    if len(s[a]["messages"]) == 0:
                        continue  # Skip empty message lists
                    if "update_num" in s[a].keys():
                        messages = s[a]["messages"][s[a]["update_num"] * (-1) :]
                    else:
                        messages = s[a]["messages"][-1:]

                    for message in messages:
                        if isinstance(message, tuple):
                            results += str(message)
                        else:
                            with io.StringIO() as buf, redirect_stdout(buf):
                                if message != "":
                                    if is_tool_result_message(message):
                                        print(f"   {message.content}")
                                    else:
                                        message.pretty_print()
                                results += buf.getvalue()

                    logger.log("info", results + "\n")

            

    except GraphRecursionError:
        logger.log("info", "Recursion limit reached. Performing final actions...")
        

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error during workflow execution: {e}")
        print(f"Error type: {type(e).__name__}")
        print(f"Full traceback:\n{error_details}")
        logger.log("error", f"Workflow execution failed: {type(e).__name__}: {e}")
        logger.log("error", f"Full traceback:\n{error_details}")

    finally:
        print("ISEA execution completed")


if __name__ == "__main__":
    main()
