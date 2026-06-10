from __future__ import annotations

import json
from typing import Any, Callable


def register_tools(*, register_tool: Callable[..., Callable], object_schema: Callable[..., dict[str, Any]]) -> None:
    """Register contestant MCP-style tools.

    This file is loaded by source/toolkits/main_mcp.py. Contestants can add,
    remove, or replace tools here when a capability is better exposed as a
    direct MCP-style function than as a SKILL.md package.
    """

    @register_tool(
        name="mock_order_lookup",
        description="Mock MCP-style tool. Returns a fixed mock order lookup result for demo purposes.",
        input_schema=object_schema(
            {
                "order_id": {
                    "type": "string",
                    "description": "Mock order id, for example MOCK-1001.",
                }
            },
            ["order_id"],
        ),
        kind="mcp",
        risk="low",
    )
    def mock_order_lookup(order_id: str) -> str:
        return json.dumps(
            {
                "mock_result": "mock-order-lookup-ok",
                "source": "mock_mcp",
                "order_id": order_id,
            },
            ensure_ascii=False,
            indent=2,
        )

    @register_tool(
        name="mock_policy_check",
        description="Mock MCP-style tool. Returns a fixed mock policy check result for demo purposes.",
        input_schema=object_schema(
            {
                "payload": {
                    "type": "string",
                    "description": "Mock payload to check.",
                }
            },
            ["payload"],
        ),
        kind="mcp",
        risk="low",
    )
    def mock_policy_check(payload: str) -> str:
        return json.dumps(
            {
                "mock_result": "mock-policy-check-ok",
                "source": "mock_mcp",
                "payload_preview": payload[:80],
            },
            ensure_ascii=False,
            indent=2,
        )
