"""Agent state definition"""
from typing import List, Optional
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field


class Location(BaseModel):
    """Location model for vulnerability locations"""
    file_path: str = Field(description="File path of your location")
    start_line: int = Field(description="Start line of your location")
    end_line: int = Field(description="End line of your location")


class Locations(BaseModel):
    """Collection of locations"""
    locations: List[Location] = Field(
        description="A list of suspicious locations, should contain at most 5 entries"
    )


class AgentState(MessagesState):
    """State for agent workflow"""
    initial_failure: str
    location: Location
    locations: List[Location]
    suggestion: str
    suggest_count: int
    fix_count: int
    patch: Optional[str]
    ready_to_locate: bool
    ready_to_fix: bool
    summary: str
    invoker: str
    next: str
    failed_location: Optional[List[Location]]
    update_num: int
    location_content: str
    problem_statement: str