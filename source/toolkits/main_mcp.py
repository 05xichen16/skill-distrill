from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable

from source.runtime.mcp_types import MCPTool, object_schema
from source.runtime.skill_runtime import get_skill_runtime


TOOLS: dict[str, MCPTool] = {}
_SOLUTION_SKILLS_LOADED = False


def register_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    kind: str = "skill",
    risk: str = "low",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
        TOOLS[name] = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema,
            func=func,
            kind=kind,
            risk=risk,
        )
        return func

    return wrapper


def list_tools() -> list[MCPTool]:
    return list(TOOLS.values())


def load_solution_skills() -> None:
    """Initialize contestant-provided SKILL.md packages and MCP-style tools."""

    global _SOLUTION_SKILLS_LOADED
    if _SOLUTION_SKILLS_LOADED:
        return
    _SOLUTION_SKILLS_LOADED = True
    get_skill_runtime()
    _load_solution_mcp_tools()


def _load_solution_mcp_tools() -> None:
    """Load optional contestant MCP-style tools from source/solution/mcp."""

    try:
        module = importlib.import_module("source.solution.mcp.contestant_tools")
    except ModuleNotFoundError as exc:
        if exc.name != "source.solution.mcp.contestant_tools":
            raise
        return

    register = getattr(module, "register_tools", None)
    if callable(register):
        register(register_tool=register_tool, object_schema=object_schema)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@register_tool(
    name="text_read_file",
    description="Read an allowed UTF-8 text file and return its content.",
    input_schema=object_schema(
        {
            "path": {
                "type": "string",
                "description": "Path to an allowed question file.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return.",
                "default": 64000,
            },
        },
        ["path"],
    ),
    risk="medium",
)
def text_read_file(path: str, max_chars: int = 64000) -> str:
    data = Path(path).read_text(encoding="utf-8")
    if len(data) > max_chars:
        return data[:max_chars] + "\n[truncated]"
    return data


@register_tool(
    name="skill_load",
    description="Load full SKILL.md instructions for a discovered skill package. Use this before applying or executing a named skill.",
    input_schema=object_schema(
        {
            "name": {
                "type": "string",
                "description": "Skill package name, for example mock_summary_skill.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters of SKILL.md to return.",
                "default": 20000,
            },
        },
        ["name"],
    ),
    risk="low",
)
def skill_load(name: str, max_chars: int = 20000) -> str:
    return get_skill_runtime().load_skill(name=name, max_chars=max_chars)


@register_tool(
    name="skill_read_resource",
    description="Read a text resource bundled inside a skill package, limited to references/ or assets/.",
    input_schema=object_schema(
        {
            "name": {
                "type": "string",
                "description": "Skill package name.",
            },
            "path": {
                "type": "string",
                "description": "Relative resource path under references/ or assets/.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return.",
                "default": 12000,
            },
        },
        ["name", "path"],
    ),
    risk="low",
)
def skill_read_resource(name: str, path: str, max_chars: int = 12000) -> str:
    return get_skill_runtime().read_resource(name=name, path=path, max_chars=max_chars)


@register_tool(
    name="skill_run",
    description="Execute a skill package entrypoint script after reading its SKILL.md instructions.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill package name.",
            },
            "arguments": {
                "type": "object",
                "description": "JSON arguments passed to the skill entrypoint on stdin.",
                "additionalProperties": True,
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    risk="medium",
)
def skill_run(name: str, arguments: dict[str, Any] | None = None) -> str:
    return get_skill_runtime().run_skill(name=name, arguments=arguments or {})


@register_tool(
    name="agent_delegate",
    description="Delegate a bounded task to an allowed sub-agent.",
    input_schema=object_schema(
        {
            "agent_name": {
                "type": "string",
                "description": "Name of the configured sub-agent.",
            },
            "task": {
                "type": "string",
                "description": "Self-contained task for the sub-agent.",
            },
            "context_text": {
                "type": "string",
                "description": "Optional compact context for the sub-agent.",
                "default": "",
            },
        },
        ["agent_name", "task"],
    ),
    kind="agent",
    risk="medium",
)
def agent_delegate(agent_name: str, task: str, context_text: str = "") -> str:
    return _json(
        {
            "error": "agent_delegate is executed by the contest runtime.",
            "agent_name": agent_name,
            "task": task,
            "context_text": context_text,
        }
    )


try:
    from fastmcp import FastMCP

    load_solution_skills()
    mcp = FastMCP("agent-contest-demo")
    for _tool in TOOLS.values():
        if _tool.name != "agent_delegate":
            mcp.tool(name=_tool.name, description=_tool.description)(_tool.func)
except Exception:
    mcp = None


if __name__ == "__main__":
    if mcp is None:
        raise SystemExit("fastmcp is not installed. The local demo runtime does not require it.")
    mcp.run()
