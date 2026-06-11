# 单题探针开关 AGENT_DEMO_ONLY_QUESTION_IDS

## Goal

平台排名规则为「重复提交取最新一次分数；提交次数仅第三层 tiebreaker」（任务书 378-383 行），因此可以用多次提交逐题排查平台变种行为。本开关让一次提交只真正解答白名单内的题目，其余题瞬间返回空串——单次运行几分钟、零多余 token、绝无 1h 截断，目标题信号最干净。

## Requirements

* 新增 env `AGENT_DEMO_ONLY_QUESTION_IDS`（逗号分隔题目 id 白名单，命名对齐既有 `AGENT_DEMO_THINKING_QUESTION_IDS` 约定，解析时 strip 空白、精确匹配 id）。
* 设置且非空时：白名单内的题正常走完整 solve 流程；白名单外的题**立即**返回 `{"id": qid, "answer": ""}`——不构建 context、零模型调用、零 skill 子进程。
* `results.json` 仍包含全部题目 id（被跳过的题 answer 为空串），格式完整性不变。
* 未设置或为空：行为与现状完全一致（全量运行）。
* 实现位置：`source/runtime/batch_runner.py` 的 `_run_one` 顶部（串行/并发两条路径的共同收口点）。
* **防呆 1（醒目横幅）**：探针模式激活时，运行开始处打印一行醒目日志（生效 id 列表 + 跳过题数），防止收官全量提交时忘关开关而无感知。
* **防呆 2（拼写错误保护）**：白名单与实际题目 id 集合的交集为空时（如手滑写 `2-3`），打印响亮警告并**视同未设置、回退全量运行**——绝不允许一次手滑产生全空提交把榜上分数清零。
* `.env` 中加注释掉的示例行，说明用法与纪律（收官提交必须保持注释/关闭）。

## Acceptance Criteria

* [ ] 设 `AGENT_DEMO_ONLY_QUESTION_IDS=3_2` 跑 10 题集：仅 3_2 进入 solve，其余 9 题无任何模型/skill 调用、answer 为空串，results.json 含全部 10 个 id。
* [ ] env 未设置/空串：与现状行为逐字节一致（现有测试零回归）。
* [ ] 白名单全部拼错（交集空）：警告 + 全量运行，不产生全空结果。
* [ ] 探针模式激活时输出横幅日志。
* [ ] 以上场景均有离线测试覆盖（不依赖真实模型端点）。

## Definition of Done

* `PYTHONIOENCODING=utf-8 python -m pytest source/eval/tests -q` 全绿（基线 188 passed，0 回归）。
* `.env` 示例注释就位。

## Decision (ADR-lite)

**Context**: 探针提交需要"只答一题"，但平台每次提交必跑全部 10 题，且「取最新一次分数」规则下误操作（忘关开关/拼错 id）会直接污染榜上成绩。
**Decision**: env 白名单 + `_run_one` 单点拦截 + 空交集回退全量 + 醒目横幅。不做 skip-list 变体、不改 start.sh、不动 results 格式。
**Consequences**: 探针期间榜上分临时塌到单题分（已知且接受）；收官前最后一笔必须是关闭开关的全量提交（操作纪律，横幅辅助提醒）。

## Out of Scope

* skip-list（黑名单）变体——YAGNI。
* 单题探针的 A/B 实验编排、提交自动化。
* start.sh / results_writer / 判分格式的任何改动。

## Technical Notes

* 平台规则依据：任务书 297 行（token 按 package_id 逐次统计）、378-383 行（取最新一次分数；积分>token>提交次数）。
* env 解析参考 `contestant_agent._should_enable_thinking` 里 `AGENT_DEMO_THINKING_QUESTION_IDS` 的逗号解析写法；`load_dotenv()` 已在 `batch_runner.run_file` 调用，子进程无需感知本开关。
* 并发路径（`AGENT_DEMO_CONCURRENCY>1`）与串行路径都经由 `_run_one`，单点改动即覆盖两者。
