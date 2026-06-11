# PRD — 全局关 thinking 降单题耗时（修「1 小时只跑 4 题」）

## 背景
华为 Agent 个人赛，正式赛题 10 道。**任务书第 281 行硬约束：单次运行最多 1 小时，超时平台强制 kill。**
正式环境实测：和模型交互轮数太多 → 单题墙钟时间被撑爆 → **一小时只跑完 4 道，6 道空答 = 直接 0 分**。
排名次序不变：**正确性 >> token >> 提交次数**。本任务为提速，绝不可牺牲正确性。

## 根因（已定位，配置层冒烟枪）
1. **`.env` `AGENT_DEMO_ENABLE_THINKING=1`（主因）**：thinking 开启使每次模型调用约 10× 慢（记忆 3_1 实测）。
   该 env 变量被 **skill 子进程继承**，导致三个重型 skill（`prompt_learn_classify`/`spec_qa`/`sensitive_scan`，
   它们代码默认是 `False`）也被覆盖成 `True`。
2. **重型 skill 调用次数高**：`prompt_learn_classify`（3_1）逐张分类整个验证集 ≈ 100 次模型调用
   （`scripts/run.py:563-595`，内并发仅 4）；`spec_qa`（1_2）每子问题一次 ×25K 上下文。100 次 ×10 倍慢 → 单 3_1 ~15-20 分钟。
3. **`AGENT_DEMO_CONCURRENCY=1` 题目全串行**：墙钟 = 各题耗时之和，前几道重题一拖，后面轮不到。

## 目标
把单题墙钟时间砍下来，让 10 道题在 1 小时内全部跑完且每题都有产出，**不引入正确性回归**。
本任务动两个提速杠杆：「单次调用耗时」最大头（thinking 全局关）+「题目串行」（题级并发=3）。墙钟兜底另议。

## 范围内（必须做）
1. **全局关 thinking**：`.env` 置 `AGENT_DEMO_ENABLE_THINKING=0`。主循环与所有 skill 子进程一并关闭。
2. **保留按题路由钩子**：`ContestantAgent._should_enable_thinking(question)` 改为
   - 代码默认 `False`（与全局关一致，即便 `.env` 缺失也默认关）；
   - 支持数据驱动的按题 id 白名单 env `AGENT_DEMO_THINKING_QUESTION_IDS=<id逗号分隔>`：命中的题单独开 thinking，
     无需改代码即可对个别确需推理的隐藏变种题开开关。
3. **题级并发=3**（用户已拍板）：`.env` 置 `AGENT_DEMO_CONCURRENCY=3`，墙钟从「各题耗时之和」转向「约最慢那道」。
   机制在 `source/runtime/batch_runner.py`：`=1` 或题数≤1 走 `_run_serial`，`>1` 且题数>1 走 `_run_concurrent`
   （`asyncio.Semaphore` 卡并发、`slots[index]` 按原始顺序存结果、每题完成即 flush）。
   - skill 子进程 worker（`PROMPT_LEARN_WORKERS` / `SPEC_QA_WORKERS`）**维持默认 4**，不动。
   - ⚠️ 峰值网关在途请求 ≈ 并发数 × 单题 skill worker 数（峰值约 12）；若网关限流 / RemoteDisconnect 再下调。
4. **回归保护**：改后跑离线单测 + 回归台，守住白送分（1_1≥2 / 1_3≥2 / 3_2≥5），exit 0。

## 范围外（本任务不做，留作 fast-follow）
- **墙钟软截止兜底**（~50min 停新题并 flush）：留作 fast-follow，若 thinking-off + 并发=3 后生产仍偏紧再加。
- **`MAX_ITER`/`TIMEOUT` 收紧**：不动，避免对多工具题/大上下文题引入截断风险（正确性优先）。
- **调高 skill `*_WORKERS`**：不动（保持默认 4），避免叠加并发后冲爆网关。

## 验收
- `.env` 改两行：`AGENT_DEMO_ENABLE_THINKING=0` 与 `AGENT_DEMO_CONCURRENCY=3`；其余 key 不变（网关三 key、skill `*_WORKERS` 默认 4）。
- `_should_enable_thinking`：无 env 时返回 False；`AGENT_DEMO_THINKING_QUESTION_IDS` 命中题返回 True、未命中返回 False。
- `BatchRunner` 在 `AGENT_DEMO_CONCURRENCY=3` 下 10 题走 `_run_concurrent`（不落 `_run_serial`）。
- `python -m pytest source/eval/tests`（或现有离线单测）全绿；回归台 exit 0，白送分阈值守住。
- 不引入第三方依赖（Python 3.9，纯标准库）。

## 关键风险
- thinking-off 对某隐藏变种推理题可能略降准 → 用 `AGENT_DEMO_THINKING_QUESTION_IDS` 单独补救；记忆显示已知题（3_1/2_2/1_2）关掉持平或更准，风险低。
- 真机网关耗时与本地 DashScope 不同 → 本地只能验「正确性不回归」，最终提速需用户在生产跑一轮确认。
