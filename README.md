# Agent 大赛 Python 最小 Demo

这是一个可以直接运行的 Agent 大赛最小 demo。赛方平台传入只含题面的运行题目 JSON，参赛系统接收题目并输出统一答案。

一句话能力说明：本 demo 提供“运行题目 JSON -> 主 Agent 编排 -> SKILL.md skill / MCP-style tool / sub-agent 调用 -> 统一结果输出”的最小闭环。

快速运行：

```bash
bash start.sh source/examples/questions.json source/outputs/result.json
```

赛方平台传入自己的运行题目文件和结果输出路径：

```bash
bash start.sh <questions_json> <result_json> [package_id]
```

第三个参数可选；传入后会作为 HTTP header `package_id` 透传给模型网关。

用户自己测试时，可以直接修改 `source/examples/questions.json`，或把自己的题目文件作为第一个参数传入，并把结果路径作为第二个参数。

默认样例题覆盖五条链路：普通回答、附件读取、mock MCP-style tool、mock Skill、mock sub-agent。

依赖约定：

```text
requirements.txt    Python 依赖清单，默认留空
```

`start.sh` 里预留了注释掉的 venv 和 pip install 命令。需要第三方包时，把包写进 `requirements.txt`，再按需解除注释；默认运行不会联网安装。
