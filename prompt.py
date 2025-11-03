from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from prompts import (
    fixer,
    suggester,
    locator,
    system_template,
) 

locator_template = ChatPromptTemplate.from_messages([
    ("system", system_template + locator), 
    MessagesPlaceholder(variable_name="messages")
],)

suggester_template = ChatPromptTemplate.from_messages([
    ("system", system_template + suggester),
    MessagesPlaceholder(variable_name="messages")
])


fixer_template = ChatPromptTemplate.from_messages([
    ("system", system_template + fixer),
    MessagesPlaceholder(variable_name="messages")
])

ANALYZE_PROMPT = (
    "Let's analyze collected context first.\n"
    "If an API call could not find any code, you should think about what other API calls you can make to get more context.\n"
    "If an API call returns some result, you should analyze the result and think about these questions:\n"
    "1. What does this part of the code/file do?\n"
    "2. How does this part of code/file's behavior influence the failing test(s)?\n"
    "3. What is the relationship between this part of the code/file and the bug?\n"
)