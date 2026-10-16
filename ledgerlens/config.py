"""Runtime configuration, environment-driven so the same code runs locally and on any deployment."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    falkordb_host: str = os.environ.get("FALKORDB_HOST", "127.0.0.1")
    falkordb_port: int = int(os.environ.get("FALKORDB_PORT", "17287"))
    falkordb_username: str = os.environ.get("FALKORDB_USERNAME", "")
    falkordb_password: str = os.environ.get("FALKORDB_PASSWORD", "")

    llm_base_url: str = os.environ.get("LLM_BASE_URL", "")
    llm_api_key: str = os.environ.get("LLM_API_KEY", "")
    llm_model: str = os.environ.get("LLM_MODEL", "glm-5.3")

    llm_max_tool_rounds: int = int(os.environ.get("LLM_MAX_TOOL_ROUNDS", "14"))

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)


CONFIG = Config()
