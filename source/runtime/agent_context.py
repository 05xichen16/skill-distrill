from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source.runtime.mcp_client import LocalMCPClient


@dataclass
class AgentContext:
    question: dict[str, Any]
    question_dir: Path
    allowed_file_paths: list[Path]
    allowed_tools: list[str]
    allowed_agents: list[str]
    mcp: LocalMCPClient

    def is_tool_allowed(self, name: str) -> bool:
        return name == "agent_delegate" and bool(self.allowed_agents) or name in self.allowed_tools

    def is_agent_allowed(self, name: str) -> bool:
        return name in self.allowed_agents

    @property
    def available_tools(self) -> list[str]:
        return self.allowed_tools

    @property
    def available_agents(self) -> list[str]:
        return self.allowed_agents

    @property
    def available_skills(self) -> list[dict[str, Any]]:
        return self.mcp.skill_summaries()

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> Any:
        return await self.mcp.call_tool(
            name,
            args or {},
            runtime_context={
                "question_id": self.question.get("id"),
                "question_dir": str(self.question_dir),
                "allowed_file_paths": [str(path) for path in self.allowed_file_paths],
                "allowed_tools": self.allowed_tools,
                "allowed_agents": self.allowed_agents,
            },
        )
