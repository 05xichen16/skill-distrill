# PRD — 补 1_4 接口测试 + 3_3 wiki 定位 skill

## 背景
华为 Agent 个人赛，正式赛题 10 道、单次运行 ≤1 小时。当前 1_4(+2,ratio) 与 3_3(+5,list_equal) **无专用 skill → 白丢 7 分**（本地 DashScope 实测各 0 分）。本机 18081(接口)/18080(wiki) 服务已由用户启动。
排名：**正确性 >> token >> 提交次数**。正式赛是隐藏变种（explanation 反复强调接口/数据/口径都可能变）——**禁止硬编码任何公开答案/ID/文本**，必须做通用解法。
研究已落盘：`research/1_4-interface.md`、`research/3_3-wiki.md`、`research/grading-semantics.md`、`research/skill-template-notes.md`（含服务契约、判分语义、30 个参考答案反向追溯结论、skill 范式）。

## 目标
新增两个**通用、纯标准库、自动发现**的 skill，照搬 `spec_qa` 范式（目录结构 / `_runtime` 注入 / `_model_config` 模型调用 / Windows 编码 IO / 优雅降级 / `answer` 输出契约）。判分用确定性代码、LLM 只做"选择/翻译"不碰最终文本，扛隐藏变种。

## 设计决策（研究背书，已采纳）
1. **skill 命名/落地**：`source/solution/skills/interface_test/`（1_4）、`source/solution/skills/wiki_dialog/`（3_3）。各含 `SKILL.md`+`skill.json`+`scripts/run.py`，自动发现、无需中心注册。
2. **1_4 分工**：LLM 把每条用例的自然语言 `description` 解析成**结构化 HTTP 步骤 JSON**（method/path/query/body、对照 api_doc 校正、标读/写、指明校验哪一次响应）；**断言判定全在代码**（status + expectedFields 存在性 + expectedValues 精确相等，点路径解析），确定性最高。
3. **3_3 分工**：预加载**权威候选池**（DB 带 `message_actions` 标注的 messages + Wiki `get_page` 带 `service_action_key` 的 FAQ）；LLM 只在候选池里**选一条**（输出候选标识，不生成文本）；reply/service_action 由**代码取候选原文**；persona_phrase 由**代码按 persona 规则**生成；`service_action = service_action_key_map[选中候选.key]`（从 `source_access.json` 读，不写死）。**冲突时优先 DB 标注源，缺则 wiki 标注源**（反向追溯 23/7、0 冲突验证）。

## 范围内 — Skill A：interface_test（1_4，type=ratio，详 research/1_4-interface.md §4）
1. 从 `_runtime` 定位 `测试用例接口文档/`，读 `test_cases.json`/`api_doc.md`/`auth_config.json`；baseUrl/token 配置从 `auth_config.json` 读，不写死。
2. X-Package-Id 用环境注入的 `PACKAGE_ID`/`packageId`，**整轮固定一致**；所有 18081 请求带该 header。
3. 按 test_cases **出现顺序串行**执行（写态有顺序依赖，禁并发）。每条：LLM 解析 description→步骤；**写步骤调用前先 `POST /api/auth/token` 取新 token**（单次写规则，除非用例明确测 401 复用）；执行步骤、取被校验响应。
4. 代码按 `assert` 判 pass/fail，失败记 ID。`answer` = 失败 ID **按用例顺序英文逗号 join**（位置敏感，宁缺勿多报）。
5. urllib + http.client fallback 调 18081；LLM 调用复用模板；配置/服务不可达时优雅降级不崩。

## 范围内 — Skill B：wiki_dialog（3_3，type=list_equal，详 research/3_3-wiki.md §6）
1. 定位 `IDE插件FSE/`，读 persona.md/source_access.json/dialog_tests_complex.json；`sqlite3` 读 chat_history.db。
2. 预加载候选池：DB `SELECT m.content, m.created_at, a.service_action_key FROM messages m JOIN message_actions a ON m.message_id=a.message_id`；Wiki 列页→`get_page` 收集带 `service_action_key` 的 FAQ `{a, key}`。
3. 每个 dialog（按序）：persona_phrase 代码生成（name 空→`您好老师`，否则`您好{name}总`，零空格漂移）；LLM 在候选池选最匹配 question 的一条（输出索引/标识）；reply=候选原文、key=候选 key；`service_action=service_action_key_map[key]`（须命中 `service_action_options` 之一）。
4. 题面要求提交 Wiki 更新建议的，按 `submit_update_proposal` POST（proposal_only，不影响判分但题面要求）。
5. 代码组装 `f"{id}=>{persona}|||{reply}|||{action}"`，`json.dumps` 成数组文本；`answer` = 该文本。单点失败给保守占位、**不漂元素数**。

## 范围外
- 不改现有 skill / 框架 / `.env`（thinking/并发上一任务已定）。
- 不为 1_4/3_3 引第三方依赖（纯标准库 urllib/http.client/sqlite3）。
- 不硬编码任何公开答案、ID、reply 文本、service_action、key→action 映射。
- 2_3(Java) 不在本任务（本机无环境）。

## 验收
- 两 skill 目录结构齐全、自动发现可见；`answer` 输出契约正确（1_4 逗号串 / 3_3 JSON 数组文本）。
- **离线单测**（monkeypatch 模型调用 + 可 mock HTTP/造 sqlite 夹具）：`source/eval/tests/` 各加测试，逐项验证解析/断言/候选选取/原文取用/persona 拼接/分隔符不漂；`pytest source/eval/tests` 全绿。
- **在线端到端**（服务已起 + DashScope）：各 skill 真跑一遍，对照 `question_disc.json` 打分——1_4 命中 6/6 失败用例（满分 2.0）、3_3 尽量逼近 30/30（list_equal 部分分，每元素 0.167）。**禁止硬编码**前提下验证。
- 回归台 `python -m source.eval.regression` exit 0，白送分不回归；纯标准库、Python 3.9。

## 关键风险
- **1_4**：ratio 位置敏感——**多报一个 ID 比漏报更伤**（挤位）；每写步骤须新 token；整轮固定 packageId；description→步骤靠 LLM 可能解析错（断言在代码兜底，最多影响该条）。
- **3_3**：list_equal 逐字全等最难——reply 必须候选原文（绝不让模型生成文本）、persona "总"(U+603B) 零漂移、service_action 走 key_map。最大不确定性是 LLM 选错候选（影响该元素 1/30，不污染其余）。变种改 DB/Wiki/key_map → "只选带标注候选 + 走 key_map" 机制通用。
- 本地 DashScope 不认 `enable_thinking=false`（慢、长），真机网关认；端到端打分看正确性而非速度。
