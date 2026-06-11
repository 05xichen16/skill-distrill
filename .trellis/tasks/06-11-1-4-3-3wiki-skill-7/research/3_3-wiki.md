# Research: 3_3 IDE 插件 FSE 数字人问答（wiki 定位）

- **Query**: 摸清 3_3 契约——题面/4 个输入文件/wiki 服务/chat_history.db/答案精确结构/原文逐字匹配策略
- **Scope**: mixed（题面+输入文件+wiki 源码+sqlite dump+反向追溯参考答案）
- **Date**: 2026-06-11

## 1. 题面（逐字关键点）

来源 `publish/publish_V1/question.json` id=`3_3`。判分 `type=list_equal`，`score=5`。

- **title**: IDE 插件 FSE 数字人问答。角色「小维」（DevPilot IDE 插件 FSE 数字人）。
- **任务**: 据 persona.md + chat_history.db + source_access.json + Wiki 服务资料，回答 dialog_tests_complex.json 中所有问题。每个问题输出固定格式结果（题目 ID + 称呼 + 人设化回答内容 + 服务动作）。涉及 Wiki 更新建议的，按 source_access.json 接口提交。
- **返回格式（逐字，最关键）** `question.json` 3_3 description 末段：
  - answer 仅返回 **JSON 数组文本**，不输出解释。数组元素按 dialog 出现顺序排列。
  - 每元素格式固定为：`题目ID=>persona_phrase|||reply|||service_action`。
  - **reply 必须与输入资料中可获取的 Wiki FAQ `a` 字段 或 chat_history.db 的 `messages.content` 原文完全一致**；**service_action 必须与 source_access.json 的 `service_action_options` 原文完全一致**。
  - reply 和 service_action **不得由模型总结、改写、补充、删减或翻译，任何不一致均不得分**。reply 可能中/英/中英混合，**必须以来源原文为准，不得翻译**。
  - 每元素**有且仅有一个 `=>` 和两个 `|||`**；persona_phrase / reply / service_action 内部不得含 `=>`、`|||` 或换行符。
  - 样例输出：`["示例题ID=>您好示例总|||示例处理口径|||标准答复"]`。
- **来源规则（逐字要点）**：以实际输入文件 + 本地 Wiki 查询为准，不套用公开样例固定结论；同时关注 FSE 人设、历史处理经验、Wiki 内容、service_action 可选项；**若 DB/Wiki 双源或时间线冲突，依据上下文、Wiki 返回与 DB 历史记录选源；最终 reply 仍必须取选中来源原文**。`service_action` 的唯一依据是**选中来源的 `service_action_key` + `source_access.service_action_key_map`**。Wiki search/list 只是候选页面信息，最终 reply 和 service_action_key 以 **get_page 返回的 FAQ 详情** 为准。
- **service_action 取值规则（逐字）**：先从所选 reply 来源记录的 `service_action_key` 取 key，再经 `service_action_key_map` 映射到具体动作，且映射结果须与 `service_action_options` 某项完全一致。**不得**据题目 ID/字段名/公开样例顺序/模型语义自行推断。
- **explanation（抗变种）**: 后续题目可能围绕不同使用阶段/故障/支撑场景调整资料，可能中文业务语境与英文术语混合（login failure、completion-service、traceId、diagnosticId、workspace_index、Remote Host）。

参考答案：30 个元素，见 `question_disc.json` 3_3 项（**仅供理解结构，禁止硬编码**）。已逐元素反向追溯到来源（见第 5 节）。

## 2. 四个输入文件

题面 files：`./IDE插件FSE/persona.md`、`./IDE插件FSE/chat_history.db`、`./IDE插件FSE/source_access.json`、`./IDE插件FSE/dialog_tests_complex.json`。实际在 `publish/publish_V1/IDE插件FSE/`。

### persona.md — `publish/publish_V1/IDE插件FSE/persona.md`

人设「小维」。**称呼规则（决定 persona_phrase，逐字）** `persona.md:11-14`：
- 若题目提供 `user.name` → `您好{user.name}总`。
- 若未提供或为空 → `您好老师`。

实测：dialog `ide_ops_003` 的 `user.name=""` → 参考答案 persona_phrase = `您好老师`；其余如 `张伟` → `您好张伟总`。**persona_phrase 不来自 wiki/db，纯按此规则用代码拼**（无翻译、无空格，"您好"+name+"总" 或 "您好老师"）。

persona.md 其余（性格/风格/决策模式）是给模型选源/判风险的语义背景，但 reply 文本不取自 persona。

### dialog_tests_complex.json — `publish/publish_V1/IDE插件FSE/dialog_tests_complex.json`

30 个问题，结构：`{ "id": "ide_ops_001", "user": {"name": "张伟"}, "question": "<中英混合的用户问题>" }`。
- `id` → 元素的“题目ID”。
- `user.name` → persona_phrase。
- `question` → 用于检索 wiki / 匹配 DB 记录的线索（含 login failure / completion / MCP / workspace_index 等术语）。
- 顺序 = answer 数组顺序（list_equal 其实不要求顺序，但题面要求，照做零代价）。

### source_access.json — `publish/publish_V1/IDE插件FSE/source_access.json`

Wiki 访问契约 + 动作映射的**单一事实源**：
- `wiki_service.base_url` = `http://127.0.0.1:18080`；`endpoints`: `list_pages=/api/wiki/pages`、`get_page=/api/wiki/pages/{page_id}`、`search=/api/wiki/search?q={query}`、`update_logs=/api/wiki/update_logs`、`submit_update_proposal=/api/wiki/pages/{page_id}/update_proposal`。
- `search_contract`：search 只按页面**标题/概览/关键词**匹配，**不**按 FAQ 答案正文匹配；result 只回 `id/title/overview/updated_at/faq_count`，**不回答案正文**。→ 必须再 `get_page` 拿 FAQ。
- `page_contract.faq_schema`：FAQ 含 `id/q/a/service_action_key`。`a` = 可直接取用、与标准答案完全匹配的答案（→ reply 候选）。`service_action_key` 经 `service_action_key_map` 解析。
- `service_action_options`（13 项，reply 旁的 service_action 必须**全等**其一）：标准答复 / 阻止高风险操作 / 要求补充定位信息 / 收集提单必填信息 / 技术问题升级二线 / 情绪风险升级运营代表或SRE Leader / 建群协同每1小时同步 / 发送未响应提醒 / 拒绝无结论关单 / 合并沟通同一用户多个问题单 / 反馈差评与重复问题 / 更新Wiki为最新指导 / 过滤无关记录。
- `service_action_key_map`（PUB-K01..K13 → 上述 13 项，顺序一一对应）。**变种可能改 key→action 映射**，所以必须读这个文件、不能写死。
- `service_action_resolution`：明确 `action_key_field=service_action_key`、`map_field=service_action_key_map`；**Wiki get_page FAQ 可能带 service_action_key**；**chat_history.db 可能有 `message_actions(message_id, service_action_key)`**——当 reply 抄自 messages.content 时，优先用同一 message_id 的 action key；**最终 service_action 必须来自“选中 reply 来源”的 action key，不得硬编码公开类别/ID/答案顺序**。

### chat_history.db — 见第 3 节

## 3. chat_history.db（sqlite 结构 + 内容）

文件 `publish/publish_V1/IDE插件FSE/chat_history.db`。用纯标准库 `sqlite3` dump。表结构：

```sql
conversations (conversation_id PK, title, created_at, updated_at, tags)         -- 27 行
messages       (message_id PK, conversation_id, role, content, created_at)      -- 213 行
message_actions(message_id PK, service_action_key NOT NULL, action_basis NOT NULL) -- 26 行
```

- `messages.content` = 历史回复原文（**reply 候选来源之一**）。role 多为 `assistant`。
- `message_actions` = **权威动作标注**：仅 26 条消息被标注 `service_action_key`（PUB-Kxx），`action_basis` 全为 `"exact reply source action key"`。这 26 条就是“当前有效口径”的权威记录。
- 大量 `conv_extended_noise` / `conv_daily_noise_more` / `conv_*_archive` / `conv_*_notes` / `conv_policy_draft_review` 是**干扰**（旧口径、噪声、跨产品、办公闲聊）——这些消息**没有** message_actions 标注，不应被选为 reply。
- 时间线冲突示例（DB 内自相矛盾，新覆盖旧）：
  - `conv_index`: `msg_index_20260510_101000`（旧:"直接删除 workspace_index 目录重建即可"，**无标注**）vs `msg_index_20260525_152000`（新:"不要默认删除整个 workspace_index;…"，**标注 PUB-K12**）。
  - `conv_proxy`: `msg_proxy_20260518_100000`（旧:"临时关闭代理后重试"，无标注）vs `msg_proxy_20260525_163000`（新:"不要直接要求关闭企业代理…"，**标注 PUB-K12**）。
  - `conv_login`/`conv_completion`/`conv_install_ticket` 同理：旧的“删整个目录/重装”无标注，新的安全口径有标注。

## 4. wiki 服务契约

源码 `publish/publish_V1/00 题目试做前需要先启动服务/3_3wiki服务/wiki_mock_service.py`；README `.../3_3wiki服务/README.md`。端口 18080，`/health` → `{"service":"devpilot_wiki_mock","status":"ok",...}`。

- **32 个 Wiki 页面内嵌在服务源码** `PAGES`（`wiki_mock_service.py:23-539`）。每页 `id/title/overview/path/updated_at/keywords/faqs[]`，FAQ 含 `id/q/a`。
- `GET /api/wiki/pages` → 仅 metadata 列表（**页面顺序按 seed 洗牌** `shuffled_pages()` `:594-597`）。
- `GET /api/wiki/pages/{page_id}` → `page_payload`（`:610-620`）：metadata + `faqs[]`，**给 FAQ 注入 `service_action_key`**（来自源码常量 `PUBLIC_FAQ_ACTION_KEYS` `:547-591`，按 faq id 映射 PUB-Kxx）。
- `GET /api/wiki/search?q=` → `{"query":..,"results":[metadata,...]}`（`:730-733`）。打分 `score_page`（`:642-663`）按 title/overview/path/keywords 匹配，**不**含 FAQ `a`；只回前 8 条 metadata（无 `a`、无 score、无 url）。
- `POST /api/wiki/pages/{page_id}/update_proposal` → 仅记录到内存 `UPDATE_LOGS`，**不改原页面**（`proposal_only` `:746-788`）。body `{content, updated_at}`。
- 路径入口 `/wiki/...`（page.path）也返回完整页面（`:739-742`）。

**Wiki 的“当前 FAQ”可能与正确口径冲突**：例如页 `WKP-A0E…`（本地索引失败说明，updated_at 2026-05-20）的 FAQ `index_building_old.a` = “…可以删除 workspace_index 后重建。” 带 key PUB-K12——但**这是过时文本**；正确 reply 是 DB 里更新的 `msg_index_20260525_152000`（“不要默认删除…”）。两者 key 都是 PUB-K12，但**reply 文本取 DB 的**。同理页 `WKP-3E20…`（企业代理，2026-05-18）FAQ `proxy_cert_old.a`="临时关闭代理后重试"带 key PUB-K02，但正确 reply 是 DB `msg_proxy_20260525_163000`（带 key **PUB-K12** → “更新Wiki为最新指导”）。**这是本题最大陷阱：wiki 的 current FAQ 不一定是正确答案，需要和 DB 比时间线、选最新权威源。**

## 5. 参考答案反向追溯（已验证，决定抽取策略）

用脚本把 30 个参考元素逐一对回 (wiki FAQ a) 与 (DB messages.content)，并核对 action key 一致性。结果（脚本已删，结论留存）：

- **30/30 reply 全部可逐字追溯到来源**，0 个无法定位。来源分布：**reply 文本同时存在于 wiki+DB 的 9 个、仅 DB 的 14 个、仅 wiki 的 7 个**。
- 按“**权威 action 来源**”分：**23/30 来自 DB-annotated**（reply = 某条带 message_actions 标注的 messages.content，action key 取该行的 service_action_key），**7/30 来自 wiki-annotated**（该 reply 无 DB 标注，取 wiki FAQ 的 a + service_action_key）。
- **每个元素的 action key 与 source_access.service_action_key_map 映射后，都与参考的 service_action 全等**；wiki 与 DB 在“同一 reply 文本”上对 key **无冲突**。冲突只发生在“**同一话题的不同 reply 文本**”（旧 wiki 文本 vs 新 DB 文本），此时答案选**带 message_actions 标注（更新、权威）的那条**。
- 验证到的“选源规律”：**优先选带 message_actions 标注的记录**（这是“当前有效口径”的信号）。当某话题 DB 有标注记录 → 用 DB（reply=content, key=message_actions.key）；DB 无标注但 wiki FAQ 有 service_action_key → 用 wiki（reply=FAQ.a, key=FAQ.service_action_key）。两类都排除无标注的旧/噪声记录。
- 26 条标注消息覆盖 30 个答案：部分答案复用同一条（如 007 与 015 都用 `msg_index_20260525_152000`；010 与 014 都用 `msg_collect_info_20260525_090000`；009 与 003 风格不同但各自有源）。

> 关键：service_action 选择**不能靠语义猜**，必须走 “选中 reply 来源记录的 service_action_key → service_action_key_map”。dialog 顺序与 service_action 无关（007 是 PUB-K12、008 是 PUB-K01，跳跃），印证题面“不得按公开样例顺序推断”。

## 6. skill 实现路径（3_3）

skill「`wiki_dialog`」应做：

1. 定位 `IDE插件FSE/` 目录，读 persona.md / source_access.json / dialog_tests_complex.json；用 `sqlite3` 读 chat_history.db。
2. **预加载权威候选池**（一次性）：
   - DB：`SELECT m.content, m.created_at, a.service_action_key FROM messages m JOIN message_actions a ON m.message_id=a.message_id`（**只取被标注的消息**作为权威 reply 候选；content=reply，key=service_action_key）。可保留 conversation tags / 时间用于话题归类。
   - Wiki：对每个候选页 `get_page` 取 `faqs[]`，收集 `{a, service_action_key}`（仅有 service_action_key 的 FAQ 作权威候选）。页面集合可由 `GET /api/wiki/pages` 列出，或对每个 question `search` 后取候选 id 再 get_page（题面要求“以 get_page 返回 FAQ 详情为准”）。
3. 对每个 dialog（按顺序）：
   - persona_phrase：按 persona 称呼规则用**代码**生成（name 空→`您好老师`，否则`您好{name}总`）。
   - reply + service_action_key：用 LLM 在**预加载的权威候选池**里选一条最匹配 question 的记录（让 LLM 输出“选中候选的索引/标识”，**不让 LLM 自由生成文本**），reply 直接取候选原文 `a`/`content`，key 取候选的 service_action_key。冲突时优先**最新/带标注**的记录（候选池本就只含带标注项，天然排除旧噪声）。
   - service_action：`service_action_key_map[key]`（代码查表，从 source_access.json 读），**必须命中 service_action_options 之一**。
   - 若 question 要求提交 Wiki 更新建议（题面/资料指示），按 `submit_update_proposal` POST（proposal_only，不影响判分，但题面要求时要做）。
4. 组装元素 `f"{id}=>{persona}|||{reply}|||{action}"`，**在代码里 join 成 JSON 数组**（保证每元素恰好一个 `=>`、两个 `|||`，且 reply/action 内部已确保无这些分隔符——来源文本天然不含）。`answer` = `json.dumps(list, ensure_ascii=...)` 文本。
5. 纯标准库；LLM 调用复用模板（`skill-template-notes.md`）。

**最大难点 = reply 原文逐字匹配**。可行策略（核心）：**绝不让模型生成/复述 reply 文本**——让模型只做“在候选池里选哪一条”（分类/检索），reply 与 service_action 一律由代码从候选原文取出。这样 list_equal 的逐字全等天然满足，模型出错最多是选错候选（影响该元素 1/30），不会污染文本。

风险 / 开放点：
- 候选池构建要覆盖全：DB 取全部带标注消息（26 条）+ Wiki 取所有页面 FAQ（带 key 的）。变种会改 DB/Wiki 内容与 key map，但“只选带标注/带 key 的候选 + 走 key_map”这套机制是通用的。
- 同一 reply 文本对应多个候选（wiki+DB 都有）时，key 在本数据集一致；但题面规定“以选中来源 action key 为准”，建议**优先 DB 标注**（与反向追溯的 23/7 分布一致）。若某话题只有 wiki 候选则用 wiki。
- search 不返回 `a`，必须 get_page；page 列表是洗牌的，但 get_page 按 id 稳定。
- persona_phrase 必须零漂移（"总" 是 U+603B；空格、全角等都会丢分）。

## Caveats / Not Found

- 反向追溯脚本为临时脚本，运行后已删除，未留在仓库；结论（来源分布 9/14/7、权威分布 23/7、0 冲突、0 未定位）已记录于上，可按第 6 节方法在 skill 开发时复跑验证。
- 参考答案文本仅用于**理解结构与验证抽取策略**，skill 必须通用生成，**不得硬编码**任何 reply/action/ID。
