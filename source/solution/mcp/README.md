# MCP-style Tools

This directory is for contestant-provided MCP-style tool extensions.

The contest runtime loads:

```text
source/solution/mcp/contestant_tools.py
```

The public demo includes two mock tools:

```text
mock_order_lookup  Return a fixed mock order lookup result.
mock_policy_check  Return a fixed mock policy check result.
```

Export a `register_tools` function:

```python
def register_tools(*, register_tool, object_schema):
    @register_tool(
        name="my_tool",
        description="Describe when to use this tool.",
        input_schema=object_schema(
            {"text": {"type": "string"}},
            ["text"],
        ),
    )
    def my_tool(text: str) -> str:
        return text
```

Use this folder for direct MCP-style tools. Use `source/solution/skills/` when
the capability should be represented as a `SKILL.md` package with instructions,
resources, and optional executable scripts. Use `source/solution/agents/` when
the capability should run as a delegated sub-agent.
