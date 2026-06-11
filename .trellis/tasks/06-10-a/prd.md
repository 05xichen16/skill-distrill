# PRD — 比赛框架硬化（阶段 A）

## 背景
华为 Agent 个人赛（Qwen3.5，OpenAI 兼容网关）。正式赛题 2026-06-11 08:30 公布。
排名：积分（按 level 加权）> 总 token（少者优先）> 提交次数（少者优先）。
→ **正确性 >> token >> 提交次数**。token 仅在积分打平时生效，绝不为省 token 牺牲正确性。

提交契约（不可破坏）：根目录 `start.sh` 三参数 `question_path result_path package_id`；
读题写 `results.json` 为 `[{id, answer}]`；`.env` 必含 `MODEL_CHAT_COMPLETIONS_URL/MODEL_API_KEY/MODEL_NAME`。
全 `source/` 均为我方可改代码。

## 目标（阶段 A：与具体赛题无关的通用底座）
把现有 demo 的硬伤补齐，做到「稳、准、省、通用」，明天拿题直接高起点。

## 范围内（必须做）
1. **多模态图片**（最高优先）：检测 `files` 中图片（png/jpg/jpeg/webp/bmp/gif），读字节→base64→
   拼 `data:<mime>;base64,...` 的 `image_url` content 块，随首条 user 消息注入；非图片仍走 `text_read_file`。
   native 与 json-fallback 两条回路都要带上图片。
2. **判题致命项**：
   - `.env` 增加 `MODEL_CHAT_COMPLETIONS_URL`（与网关一致），保留 `MODEL_BASE_URL`。
   - 模型请求**同时**发 `package_id` 与 `packageId` 两个 header（任务书自相矛盾，双保险）。
3. **保留题面信息**：`public_question_fields` 保留 `title/explanation` 及题目自带 `tools/skills/sub_agents`
   提示；prompt 中带上 title+explanation（explanation 是抗变种/泛化关键）。幂等（被调用两次仍正确）。
4. **enable_thinking 开关**：payload 支持 `chat_template_kwargs.enable_thinking`，按调用可覆盖；
   阶段 A 默认开（保正确），预留 `_should_enable_thinking(question)` 路由钩子供阶段 B 调。
5. **健壮性**：网关调用加指数退避重试（5xx/超时/连接/RemoteDisconnected，重试 2~3 次）；
   每题失败降级为「无工具单次直答」兜底，杜绝空答案。
6. **确定性答案清洗**（0 token）：去「答案：/最终答案：/Answer:」等前缀、去 markdown 围栏/引号、trim。
7. **并发开关**：`batch_runner` 加 `AGENT_DEMO_CONCURRENCY`（默认 1=串行），>1 时 Semaphore 并发 + 完成即写盘。
   **默认串行**（用户已确认）。
8. **token 用量日志**（best-effort）：能拿到 `usage` 就打到 stderr，供阶段 B 定位烧 token 的题。

## 范围外（阶段 B 再做）
- 针对具体题型的确定性 skill 库、few-shot、复核/自一致性、分隔符按题归一、并发实际开启与调参。

## 验收
- 现有 `questions.json` 5 条链路（直答/读文件/MCP工具/skill/sub-agent）全部端到端通过。
- 自造一张告警截图，图像题能走多模态返回结果。
- 任一题异常不致空答案；`.env` 三 key 齐备；header 双发；串行默认不回归。
- 不引入第三方依赖（Python 3.9.9，纯标准库）。

## 关键风险
- 大图 base64 体积（无 PIL 不能缩放）→ 阶段 B 关注，必要时加字节上限告警。
- 网关是否支持 native `tools` 字段未知 → 已有 json-fallback 兜底，明天首测确认。
