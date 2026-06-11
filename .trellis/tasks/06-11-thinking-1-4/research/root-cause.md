# 研究：为什么 1 小时只跑完 4 道题

## 硬约束
- `任务书.md:281`：单次运行最多 1 小时，超时平台强制终止。`results.json` 每题完成即 flush，
  故已完成答案在 kill 后仍保留（`batch_runner.py:45,68-69`）。
- 真题 10 道（`publish/publish_V1/question.json`：1_1..3_3）。跑完 4 道 → 6 道空答 = 0 分。

## 调用链与耗时来源
- 入口：`start.sh` → `source.main` → `BatchRunner.run_file`。
- `AGENT_DEMO_CONCURRENCY` 默认 1（`batch_runner.py:29-31`）→ 题目串行，墙钟 = 各题之和。
- 每题主循环 `_run_native_tool_loop`：最多 `AGENT_DEMO_MAX_ITER`(=6) 次模型调用（`contestant_agent.py:217-219`）。
- 主循环 `_should_enable_thinking` 默认 `env_bool("AGENT_DEMO_ENABLE_THINKING", True)`（`contestant_agent.py:79-87`）。
- 模型请求把 `enable_thinking` 放进 `chat_template_kwargs`（`openai_chat_client.py:56-64`）。

## 冒烟枪：生产 `.env`
```
AGENT_DEMO_ENABLE_THINKING=1   # thinking 开 → 每次调用 ~10× 慢；被 skill 子进程继承
AGENT_DEMO_CONCURRENCY=1       # 题目串行
AGENT_DEMO_MAX_ITER=6
AGENT_DEMO_TIMEOUT_SECONDS=120
```
- skill 子进程读 `AGENT_DEMO_ENABLE_THINKING`，代码默认 `False`，但被 `.env` 的 `=1` 覆盖：
  `prompt_learn_classify/scripts/run.py:326`、`spec_qa/scripts/run.py:548`（`sensitive_scan` 硬编码 False）。
- 重型调用次数：`prompt_learn_classify` 逐张分类整个验证集 ≈100 次模型调用、内并发仅 4
  （`run.py:563-595`，`PROMPT_LEARN_WORKERS` 默认 4）；`spec_qa` 每子问题一次 ×25K 上下文。

## 量级估算
100 次调用 ÷ 4 并发 ≈ 25 波；thinking-on 每波数十秒 → 单 3_1 ~15-20 分钟。
叠加串行 + 其余重题，4 道题即耗尽 1 小时。

## 修复杠杆（按影响 / 风险）
1. **关 thinking（最大头，风险最低）**：`ENABLE_THINKING=0`。记忆实测 3_1 off 85%>on 75%，2_2/1_2 本就 off 满分。← 本任务做。
2. 题级并发（中性提速，需网关承压）：用户「先不管」。
3. 墙钟软截止兜底（纯保险）：fast-follow。
4. `MAX_ITER`/`TIMEOUT` 收紧：不动，避免截断风险。

## 决策（用户已拍板）
- thinking：全局关 + 保留按题路由钩子（`AGENT_DEMO_THINKING_QUESTION_IDS` 白名单）。
- 并发：保持 1 不动。
