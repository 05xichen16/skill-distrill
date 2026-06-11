# 平台 31.67/102 根因分析（行号级，4 个 Explore agent 交叉核实 2026-06-11）

## 大前提（决定全部修法方向）

`题目/` 下 10 个 txt = 用户从平台抄回的真题题面，**与 `publish/publish_V1/question.json` 公开集题面逐字相同**（连 2_3 的 10 个隐藏用例输入 5000…500000、1_2 的十问、3_2 题面里的 50000 阈值数字都没变）。**⇒ 隐藏变种只变附件数据**：消息措辞、CSV 内容、邮件正文、DB/Wiki 内容、Java 源码错误位置与税率表。explanation 中的"变化点"描述的是数据变化（如 3_2 "审计规则的阈值也不是固定值" = 变种题面 description 里的阈值数字会变，解析时不能硬编码）。

平台分（题号=平台序号）：1_1=3/6、1_2=4.2/6、1_3=5/6、1_4=1.07/6、2_1=6/9、2_2=0/9、2_3=0/15、3_1=12.4/15、3_2=0/15、3_3=0/15。

## 2_3 = 0/15 — java_tax_calculator 根本不跑 Java

* skill **不调 javac/java 跑业务**：python 复刻税率（`run.py:104-112` calculate_tax），参数从源码正则抽 `TAX_BRACKETS_ENCODED`/`DEDUCTION_POINT_ENCODED` Base64 解码（`run.py:88-94` + `:136` decode_parameters）。
* 这两个字段名是**公开版源码实现细节**。变种源码（错误位置/税率表变）没有它们 → decode_parameters 抛异常 → `run.py:149-150` catch 返回 `{"error":...}` 无 answer 字段 → router 回退模型瞎答 → 11 段全错（连第一段 contain[21.0.11] 都丢，证明 skill 整体没产出）。
* `java -version` 仅在 `run.py:115-129`（10s 超时，失败回退硬编码 `DEFAULT_JAVA_VERSION="openjdk version \"21.0.11\""` `run.py:13`）。skill.json timeout=30s。
* 判分：11 段，第 1 段 contain[21.0.11]，后 10 段精确值，得分=命中/11×15。题面自带 5 个示例 IO（3000→0.00 / 8000→90.00 / 15000→590.00 / 30000→2340.00 / 100000→27440.00）= 天然自校验 ground truth。
* **修法**：LLM 读源码修错→javac（报错喂回重修循环≤3）→java 跑 5 示例验证→全过跑 10 隐藏用例→真实 java -version。fallback=LLM 从注释抽税率→python。判题机有 JDK21（任务书 4.2）。

## 3_2 = 0/15 — po_compliance_audit 全硬编码 + equal 全或零

* 金额阈值 50000 硬编码：`run.py:240`。题面 explanation 明说阈值不固定（变种题面 description 里数字会变）→ 必须从题面文本解析"达到或超过 X"。
* 状态白名单硬编码：`run.py:119-125`（bad 10 词 + good 9 词，substring 匹配）。"已付款"/"settled"/"已终验"会误判。
* 审批语义=固定词表：`run.py:192-202` approval_positive 只查"批准/同意/确认/通过"等硬词；approval_covers_all 同样。题面明说附件是**多轮转发/追问**、"只批准其中一项""先评估"不算——纯正则无法判定。
* 日期仅 5 格式：`run.py:98-116`（中文年月日/ISO/M/D/Y/Mar 5, 2026/星期+ISO）。`2026.03.05`、`05-03-2026`、`5 March 2026`、`2026/03/05` 全 None → sent_date 无效 → 审批全挂。
* 容错：CSV 读失败抛异常（router 回退）；evidence 缺失/日期解析失败 → **静默判不合规**（垃圾照提交）。po_date 缺失 parse_iso 崩（`:161`）。
* equal 全等判分 → 一个 PO 判错 = 0。期望分 = P(全对)×15，判定准确率必须拉满 + 输出守卫。
* **修法**：代码骨架（CSV/角色有效期/日期比较/排序）+ LLM 判定（阈值从题面 description 解析；状态词去重后 LLM 一次分类；每封邮件 LLM 出结构化 `{approved, covers_all_items, approval_date, sender_email}`；日期扩格式+LLM 兜底）；结果守卫（空/全不合规等异常形态→抛异常回退）。

## 3_3 = 0/15 — wiki_dialog 占位输出原样提交

* 候选池空时 `run.py:930-934`：`reply=""`、`action=options[0]`、source="none" → `:936` build_element → `:947` json.dumps **原样提交**，不抛异常 → router 不回退 → 30 元素全错（list_equal 逐元素全等）。
* 候选池结构假设：DB 表 `messages`/`message_actions`、列 `content/created_at/message_id/service_action_key`、JOIN on message_id、只取有 action_key 的行（`run.py:330-377`）；wiki list_pages 返回 `pages/results/data`、页面 `id/page_id`、get_page 返回 `faqs/faq`、FAQ 对象 `q/a/service_action_key`（`:380-435,444-466`）；source_access.json 顶层 `service_action_key_map`/`service_action_options`（`:559-577`）。变种"调整 action key、Wiki 页面、DB 元数据"任一 → 候选池空。
* persona_phrase 纯代码拼（`run.py:267-277`），从 persona.md 正则抽 `{user.name}` 占位行（`:211-264`）；persona.md 改结构 → 回落硬编码默认称呼 → 30 元素 persona 段全错（每元素全等→全 0）。
* "提交 Wiki 更新建议"未实现（`:958-981` 写死 skip，需 env `WIKI_DIALOG_SUBMIT_PROPOSALS`）。
* 旧版无 skill 模型自由发挥拿 6.33/15（~12/30）。
* **修法 P0**：输出自检（reply 空率>30% / 候选池空 / 严重 warning → 抛异常回退模型，保底 6.33）。P1：DB 动态发现（PRAGMA table_info 找语义列）、wiki 字段多套兼容、persona LLM 化。

## 2_2 = 0/9 — sensitive_scan 串行 OCR 超时

* `run.py:352` for 循环逐张 OCR，单图超时 60s（`:381-388` 默认），6 图最坏 360s > skill.json:5 `timeout_seconds:300` → 子进程被 kill → router 回退模型 → ratio 4 位全偏 0。
* 本地 DashScope 单图快、串行压进 300s 所以 3.0 满分；真机网关单图 ~50-60s 必死。
* 文本部分计数逻辑已证全对（2782,3479,2299,3562 + 图 24/16/29/29 = 2806,3495,2328,3591）。手机号正则边界 `(?<!\d)1\d{10}(?!\d)` 已修。
* 敏感类型正则写死 4 类；explanation "类型可能增加" → 动态化加分项。
* **修法**：ThreadPool 有界并发（仿 `prompt_learn_classify` `run.py:593` ThreadPoolExecutor 用法 + `:606-618` 汇总）；单图失败/超时计 0 + warning 降级，不整体死。

## 1_4 = 1.07/6 — interface_test conservative-pass 少报

* 用例描述 → HTTP 步骤靠 LLM 解析（`run.py:541-560` parse_steps），35B 在变种用例上解析失败 → steps=[] → `run.py:822-826` **conservative pass（当通过，不进失败列表）**；步骤执行 error 同样 `:829-830` conservative pass。
* auth 变种 token 提取失败（`:707-711`）→ 写接口 401 → 同样被静默。失败用例大量漏报 → ratio 位置判分 18%。
* 断言只支持 expectedStatus/expectedFields/expectedValues（`:303-342`），未知断言 key 被忽略。
* **修法**：解析失败/步骤 error 不再 conservative——重试一次，仍失败标记该用例"不确定"并将整题置信度下调；不确定占比高 → 抛异常回退模型。

## 1_1 = 3/6 — date_normalize 正则树 50% < 模型 81%

* 手写决策树（`run.py:149-230`）：完整日期/昨天明天/去年今天/儿童节/工作日加法/上下周星期 N/月日推年/试用期/发货/小时偏移。
* 未匹配行 `run.py:229` raise ValueError → **整题**回退模型（粒度太粗）；变种措辞被错误正则吞掉时输出错值不 raise → 50%。
* 模型自由答历史 4.87/6（81%）。
* **修法**：逐行混合——正则高置信命中走正则，未命中/低置信**单行**走 LLM（参考 spec_qa `run.py:531-568` 的模型调用基建复制）；全文失败仍回退。

## router 零门禁（横切）

* `contestant_agent.py:106-114`：`_try_explicit_skill_route` 仅当 skill 抛异常或 `_extract_skill_answer` 返回 None（`:268-271`，只看 answer 字段存在性）才回退；**空串/占位 answer 照样提交**。`_clean_final_answer` 只做正则清理。
* **修法**：通用门禁（answer 去空白后为空、或全是占位分隔符模式 → 回退模型）+ per-skill validator 钩子（可选 callable：1_1 行数=输入行数、2_3 必须 11 段且首段含 version、3_3 reply 非空率、2_2 4 个非负整数）。

## 其余（P1）

* 1_2=4.2/6：spec_qa `_keywords`（`run.py:388-419`）无翻译桥，英文问题在中文文档检索漂移；修法=英文问先 LLM 出中文检索词。
* 2_1=6/9：purchase_clean_summary 纯正则无语义（po_id 字面匹配 `:234-242`、发票/作废词表 `:245-260`、品类关键词表 `:15-24,302-316`、币种 3 种、发票>系统金额即拒 `:347-361`）；修法=附件证据 LLM 结构化抽取，代码只算账。
* 1_3=5/6：system_issue_locator 三种 form_schema 模式都支持（`:144-177`）；module fallback 硬编码"用户管理"（`:192-194`）是隐患，P3。
* 3_1=12.4/15：≈分类准确率上限（81-85%），P3。

## 验证策略（本地无变种数据）

1. 离线单测（每个修复点）
2. **对抗扰动自测**：对公开集附件做措辞/格式/字段名扰动（邮件日期改 `2026.03.05`、状态改"已付款"、阈值改 60000、删 Java 源码 Base64 字段、DB 表改名），验证 skill 正确或正确回退
3. 回归台 `python -m source.eval.score/regression`（白送分阈值）
4. DashScope 35B-A3B 端到端全 10 题 ≥ 25.93/32 基线
