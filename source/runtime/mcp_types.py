from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class MCPTool:
    """Small tool descriptor compatible with OpenAI-style tool calling."""

    name: str
    description: str
    input_schema: JsonDict
    func: Callable[..., Any]
    kind: str = "skill"
    risk: str = "low"

    def to_openai_tool(self) -> JsonDict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    async def call(self, args: JsonDict | None = None) -> Any:
        result = self.func(**(args or {}))
        if inspect.isawaitable(result):
            return await result
        return result


def object_schema(properties: JsonDict, required: list[str] | None = None) -> JsonDict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }
