from typing import Optional
from datetime import datetime
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration settings with support for environment variables."""

    # LLM API Settings
    # openai_api_key: str = Field(default="sk-NdZukOuQQRhydvPW33Dc1e05AbCa4fE394BfD3FfB9Ac09Be", env="OPENAI_API_KEY")
    # openai_base_url: str = Field(default="https://api.holdai.top/v1", env="OPENAI_BASE_URL")
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1", env="OPENAI_BASE_URL")
    openai_model: str = Field(default="deepseek-v3", env="OPENAI_MODEL")

    claude_api_key: str = Field(default="", env="CLAUDE_API_KEY")
    claude_base_url: str = Field(default="", env="CLAUDE_BASE_URL")
    claude_model: str = Field(default="", env="CLAUDE_MODEL")

    relay_api_key: Optional[str] = Field(default=None, env="RELAY_API_KEY")
    relay_base_url: Optional[str] = Field(default=None, env="RELAY_BASE_URL")

    # Neo4j Database Settings
    neo4j_uri: str = Field(default="bolt://localhost:7687", env="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", env="NEO4J_USER")
    neo4j_password: str = Field(default="12345678", env="NEO4J_PASSWORD")

    # Project Settings
    TEST_BED: str = Field(default="", env="TEST_BED")
    PROJECT_NAME: str = Field(default="", env="PROJECT_NAME")
    INSTANCE_ID: str = Field(default="", env="INSTANCE_ID")
    PROBLEM_STATEMENT: str = Field(default="Find and fix bugs in the project", env="PROBLEM_STATEMENT")


    ROUND: str = Field(default="verified_Claude-4-Sonnet_round_c_3", env="ROUND")

    # Unified timestamp for the entire application run
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()