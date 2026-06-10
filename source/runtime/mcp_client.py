from __future__ import annotations

from pathlib import Path
from typing import Any

from source.runtime.agent_registry import AgentRegistry
from source.runtime.mcp_types import MCPTool
from source.runtime.skill_runtime import get_skill_runtime
from source.toolkits import main_mcp


class LocalMCPClient:
    """Local MCP-style client used by the contest runner.

    It exposes the same high-level operations contestants need:
    list available tools and call a tool by name. The implementation is local
    so the public demo runs without any external MCP daemon.
    """

    def __init__(self, agent_registry: AgentRegistry | None = None) -> None:
        main_mcp.load_solution_skills()
        self._tools: dict[str, MCPTool] = dict(main_mcp.TOOLS)
        self._agent_registry = agent_registry or AgentRegistry()

    def tool_names(self) -> list[str]:
        return sorted(
            name
            for name, tool in self._tools.items()
            if tool.kind != "agent"
        )

    def agent_names(self) -> list[str]:
        return self._agent_registry.names()

    def skill_names(self) -> list[str]:
        return get_skill_runtime().skill_names()

    def skill_summaries(self) -> list[dict[str, Any]]:
        return get_skill_runtime().list_skill_summaries()

    async def list_tools(
        self,
        *,
        allowed_tools: list[str] | None = None,
        allowed_agents: list[str] | None = None,
    ) -> list[MCPTool]:
        allowed_tool_set = set(allowed_tools or [])
        result = []
        for tool in self._tools.values():
            if tool.kind == "agent":
                if allowed_agents is None or allowed_agents:
                    result.append(tool)
                continue
            if allowed_tool_set and tool.name not in allowed_tool_set:
                continue
            result.append(tool)
        return result

    async def list_openai_tools(
        self,
        *,
        allowed_tools: list[str] | None = None,
        allowed_agents: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        tools = await self.list_tools(
            allowed_tools=allowed_tools,
            allowed_agents=allowed_agents,
        )
        return [tool.to_openai_tool() for tool in tools]

    async def call_tool(
        self,
        name: str,
        args: dict[str, Any] | None,
        *,
        runtime_context: dict[str, Any],
    ) -> Any:
        args = dict(args or {})
        allowed_tools = set(runtime_context.get("allowed_tools") or [])
        allowed_agents = set(runtime_context.get("allowed_agents") or [])

        if name == "agent_delegate":
            if not allowed_agents:
                raise PermissionError("No sub agents are allowed for this question.")
            agent_name = str(args.get("agent_name", ""))
            if agent_name not in allowed_agents:
                raise PermissionError(f"Agent is not allowed for this question: {agent_name}")
            return await self._agent_registry.run(
                agent_name=agent_name,
                task=str(args.get("task", "")),
                context_text=str(args.get("context_text", "")),
            )

        if allowed_tools and name not in allowed_tools:
            raise PermissionError(f"Tool is not allowed for this question: {name}")
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")

        if name == "text_read_file":
            args["path"] = str(self._resolve_allowed_file(args, runtime_context))

        return await self._tools[name].call(args)

    def _resolve_allowed_file(
        self,
        args: dict[str, Any],
        runtime_context: dict[str, Any],
    ) -> Path:
        raw_path = str(args.get("path", ""))
        question_dir = Path(runtime_context["question_dir"]).resolve()
        target = Path(raw_path)
        if not target.is_absolute():
            target = question_dir / target
        target = target.resolve()

        allowed_paths = [
            Path(path).resolve()
            for path in runtime_context.get("allowed_file_paths", [])
        ]
        if not any(self._is_allowed_file_target(target=target, allowed=allowed) for allowed in allowed_paths):
            raise PermissionError(f"File is not declared in the question: {raw_path}")
        if not target.exists():
            raise FileNotFoundError(str(target))
        if not target.is_file():
            raise IsADirectoryError(str(target))
        return target

    def _is_allowed_file_target(self, *, target: Path, allowed: Path) -> bool:
        if allowed.is_file():
            return target == allowed
        if allowed.is_dir():
            return target != allowed and target.is_relative_to(allowed)
        return target == allowed
