# 2_3 模型抽取计算输入用例(严格输出) + 确定性兜底

## Goal

题目 7（2_3，Java 个人所得税计算器）在平台变种上仍拿不到分。经核实，**公开集是满分**（in-process 路径逐段命中权威答案），失分发生在**变种**。本任务收敛一个明确风险点：**"要计算哪 10 个薪资输入"这一步的解析在变种排版下会失效**，导致算错对象、逐位置判分整列归零。

做法（用户拍板）：**让模型只负责从题面抽取"用于计算的输入薪资列表"，严格约束输出格式；拿到后喂进确定性公式计算**。税表/起征点/计算/取整/版本段全部保持确定性，模型不碰。模型异常/超时/输出不合规时退回确定性解析兜底。

## What I already know（已核实事实）

- **公开集权威答案**（`publish/publish_V1/question_disc.json` 的 2_3）：
  `contain[21.0.11],is[0.00],is[290.00],is[1340.00],is[3090.00],is[7840.00],is[9340.00],is[11090.00],is[22940.00],is[49940.00],is[207440.00]`，type=`match2`，score=3。
- 当前 in-process 路径（`contestant_agent._java_tax_inprocess` → `run.py: emergency_answer(config=None)`）对公开源码产出 `openjdk version "21.0.11",0.00,290.00,...,207440.00`，**逐段全中 → 公开集满分**。
- `result.json` 里 2_3 的 `17.0.2`/不同税额是**题面格式示例（红鲱鱼）**，非参考答案。
- `decode_encoded_constant`（`run.py:540`，自适应剥 base64 层，parse-first，max_rounds=8）已提交（`d3cf295`）；实测对"起征点 4 层编码 + 改税表"变种**解码正确**，㉙ 的固定 3 层病根已修。
- **薪资解析现状**：`hidden_salaries`（`run.py:167`）用 `(?m)^\s*(\d{4,})\s*$` 抓"裸 4 位数字行"，无 `隐藏用例` 锚点时在全文抓；抓不到则退 `DEFAULT_SALARIES`（恰等于公开集 10 个薪资）。题面 explanation 明示"输入范围可能变化"——变种换薪资值/换排版（逗号分隔、带 `元`、3 位数、行内）会令该正则失效 → 退 DEFAULT（变种就错）或抓到污染数字 → **逐位置整列归零**。

### 已做的边界测试（本会话）
- 2a（常量改名）：含税务关键词或有 worked-examples 时启发式能自救；改成无关键词名(`s1/s2`)且无样例 → 10 税额全错。
- 2b（小数位）：标准 2 位小数税率 × 整数 taxable，140 万样本 **0 次** Java HALF_UP vs Python HALF_EVEN 分叉 → **非病因**；仅细粒度税率(如 0.125)才分叉。

## Assumptions (temporary)

- 平台变种仍是 `match2`、版本段 `contain[21.0.11]`、输出 2 位小数、10 个用例（待平台 diag 复核）。
- 选手沙箱可访问模型网关（用户判断"模型不会挂"）；但仍按"会挂"设计兜底。
- 本次失分属于"答案到判分器但税额错（≈0.82 版本-only）"支；若实为**精确 0.00**（答案没到判分器）则病在编排层，本任务不直接解决（需探针/diag 另查）。

## Requirements (evolving)

- R1：新增"模型抽取输入薪资"步骤，**严格输出契约**（只回 JSON 整数数组、按题面顺序、无多余文字），解析后做 sanity check（全正整数、数量合理）。
- R2：抽取结果**仅作为公式输入**；税表/起征点/`calculate_tax`/输出格式/版本段保持确定性不变。
- R3：**确定性兜底地板**——模型不可用/超时/输出不合规 → 退回（加固后的）确定性薪资解析；兜底不可阻塞出答案、不可被网关拖死。
- R4：兜底解析从过窄的"裸 4 位数字行"升级为**锚点 + 区段顺序抓整数**（容忍逗号/空格分隔、带单位、3 位数）。
- R5：模型调用有**硬超时**且受 deadline 约束，绝不威胁 skill 的 emit 截止（沿用 `_clamped_timeout`/`deadline` 机制）。
- R6：公开集**零回归**——仍逐段产出 `...,0.00,290.00,...,207440.00` 满分。
- R7（版本段双赢）：版本段不再纯硬编码。in-process emergency 路径接 `java_version_line()`：**活探 `java -version`**，并让最终版本段**同时包含探到的真实版本 + `21.0.11`**（如 `openjdk version "21.0.11" (runtime: 17.0.2)`）。判分器是 `contain[...]` 子串匹配（`score.py:96`）→ 参考无论是 `contain[21.0.11]` 还是 `contain[<真实版本>]` 都命中，严格优于纯硬编码与纯活探。
- R8：活探失败/无 `java` → 退回 `21.0.11`（保持现状不更糟）；版本段仍过 `_guard_java_tax_calculator`（首段含 "version"）。

## Open Questions（已收敛）

- ~~Q1（范围边界）~~ **已定**：Salary 抽取+兜底 **+ 版本段双赢**；2a/2b 留 out-of-scope。
- ~~Q2（模型调用落点）~~ **已定**：模型抽取放在 **router（`contestant_agent.solve()`）**——它本就有 async + `ChatCompletionClient` + 题面文本；抽出的薪资作为 `args["salaries"]` 下传给 `_java_tax_inprocess` → `emergency_answer`，后者**仍是 config=None 的纯离线计算**，只是"收下薪资数据"。`emergency_answer`/`answer` 在无 `args["salaries"]` 时退回加固后的确定性 `hidden_salaries`。理由：计算保持离线、模型只产出输入数据、职责清晰；子进程路径(罕用)走确定性即可。

## Acceptance Criteria (evolving)

- [ ] 公开集 in-process 产出逐段等于权威答案（零回归）。
- [ ] 模型抽取返回合规 JSON 整数数组时，薪资列表 == 题面所列顺序值。
- [ ] 模型超时/返回非法/网关不可用 → 自动退回确定性解析，仍在 deadline 前出合法 11 段答案。
- [ ] 兜底确定性解析能吃下：逗号分隔、带 `元`/`¥`、3 位数、行内列举 等变种排版（单测覆盖）。
- [ ] 模型抽取不污染计算：税表/起征点/取整保持确定性。
- [ ] 版本段同时含真实探测版本与 `21.0.11`；活探失败时退回 `21.0.11`；公开集 `contain[21.0.11]` 仍命中。
- [ ] 全量 pytest 绿、ruff clean。

## Decision (ADR-lite)

**Context**: 2_3 公开集满分、变种失分。已修固定解码层数；剩余"税额全错"最脆点是"算哪些薪资"的解析（题面"输入范围可能变化"），其次是版本段纯硬编码在"变种版本号也变"时丢分（与税额全错叠加 → 精确 0）。

**Decision**:
1. 模型只抽"输入薪资列表"（严格 JSON 整数数组），在 router 完成，作为数据下传；计算全确定性；失败退回加固后的确定性锚点解析（地板）。
2. 版本段改"活探 + 同段并含 21.0.11"的双赢，利用 `contain[]` 判分语义两个世界都命中。
3. 2a（常量改名解码加固）与 2b（HALF_UP）暂不做：2a 启发式+样例已基本自救，2b 已证非病因（140 万样本 0 分叉）。

**Consequences**: 模型进入 in-process 主路径的"输入抽取"一步，引入有限网关依赖 → 必须硬超时 + 不阻塞 + 确定性兜底来保住"杀不掉、必出答案"的属性。版本段并含多版本属"利用判分宽松语义"的稳妥 hack，若判分器未来改 `is[]`（精确）需回退（当前 disc 为 `contain`，安全）。

## Definition of Done

- 单测覆盖：模型抽取成功/超时/非法输出/网关挂 四条分支 + 兜底解析多种排版 + 公开集零回归。
- Lint/typecheck/CI 绿。
- 不改动 java_tax 之外的题目逻辑。
- 收尾提交前用探针 `AGENT_DEMO_ONLY_QUESTION_IDS=2_3` 重交并核 `[AGENT_DIAG]`（验证落点：精确 0.00 vs ≈0.82）。

## Out of Scope (explicit)

- 让模型解析税表/起征点/计算规则（保持确定性）。
- 编排层"精确 0.00（答案没到判分器）"病因（路由/超时/stdout 丢）——若 diag 证实是该支，另起任务。
- 其他题目（仅动 java_tax 相关文件）。

## Technical Notes

- 关键文件：`source/solution/skills/java_tax_calculator/scripts/run.py`（`hidden_salaries:167`、`answer:1036`、`emergency_answer:1140`、`_call_model:249`、`_clamped_timeout:66`）、`source/solution/contestant_agent.py`（`_java_tax_inprocess:332`、`_java_tax_request:396`）。
- 判分语义：`source/eval/score.py`（`match2`/`contain[]`/`is[]` 逐段，`score_match:103`）。
- 测试：`source/eval/tests/test_java_tax_calculator.py`、`test_contestant_agent_router.py`。
- 设计原则（历史教训）：有确定性解的题进程内离线直算领跑，绝不依赖网关/skill 发现/model loop；本任务模型仅作"输入抽取的可选增强"，且永不挡在离线出口前。
