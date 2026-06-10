# 参赛者开发区

正式比赛通常只提交这个目录。

## 主 Agent

入口文件：

```text
contestant_agent.py
```

实现入口：

```python
class ContestantAgent:
    async def solve(self, *, question, context) -> str:
        ...
```

题目对象由赛方传入，题目不会指定应该用哪个 MCP-style tool、skill 或 sub-agent。主 Agent 负责发现能力、选择能力、调用能力和组织最终答案。`solve()` 返回的字符串会被 runtime 写入结果 JSON 的 `answer`。

主入口可以直接看到：

```text
question                         公开题面
question["files"]                可读文件或目录列表
context.available_tools          MCP-style tool 名称
context.available_skills         skill 摘要
context.available_agents         sub-agent 名称
context.call_tool(...)           工具调用入口
```

文件内容不会自动进入 prompt；需要时调用 `text_read_file`。`files` 列文件时只授权该文件，列目录时授权该目录下的文件。

## Skill 包

目录：

```text
skills/<skill_name>/
```

最小可用 skill：

```text
SKILL.md
```

可执行 skill：

```text
SKILL.md
skill.json
scripts/run.py
references/
assets/
```

`SKILL.md` 是必需入口，写给模型和开发者看的使用说明。建议在文件开头写 frontmatter：

```markdown
---
name: my_skill
description: Describe when this skill should be used.
---
```

`skill.json` 是可选执行元数据。需要让 runtime 执行脚本时，提供 `entrypoint` 和 `input_schema`。`scripts/run.py` 从 stdin 读取 JSON，向 stdout 输出结果。

当前 demo 提供 `mock_summary_skill` 作为 mock Skill 示例。它只返回固定 `mock_result`，用于展示 skill 接入链路。

主 Agent 不会直接看到每个 skill 的完整内容。它会先看到 skill 摘要，并通过这些通用工具使用 skill：

```text
skill_load            读取完整 SKILL.md
skill_read_resource   读取 references/ 或 assets/ 中的资源
skill_run             执行 skill.json 声明的 entrypoint
```

## Sub-agent 包

目录：

```text
agents/<agent_name>/
```

包结构：

```text
AGENT.md
agent.json
scripts/run.py
```

主 Agent 通过 `agent_delegate` 调用 sub-agent：

```python
await context.call_tool("agent_delegate", {
    "agent_name": "mock_review_agent",
    "task": "review mock payload",
    "context_text": "..."
})
```

## MCP-style 工具层

参赛者侧 MCP-style tools 放在：

```text
source/solution/mcp/
```

默认入口：

```text
source/solution/mcp/contestant_tools.py
```

在 `contestant_tools.py` 中导出 `register_tools`：

```python
def register_tools(*, register_tool, object_schema):
    @register_tool(
        name="my_tool",
        description="Describe when to use this tool.",
        input_schema=object_schema({"text": {"type": "string"}}, ["text"]),
    )
    def my_tool(text: str) -> str:
        return text
```

赛方统一 MCP-style 注册入口仍在：

```text
source/toolkits/main_mcp.py
```

参赛者通常不修改赛方入口。提交能力时，可以把说明型能力做成 `skills/` 下的 SKILL.md 包，把直接函数型能力放到 `mcp/`，把可委托流程放到 `agents/`，再在 `contestant_agent.py` 中编排。

当前 demo 提供两个 mock MCP-style tool 示例：`mock_order_lookup` 和 `mock_policy_check`。它们只返回固定 `mock_result`，用于展示 MCP-style tool 接入链路。
