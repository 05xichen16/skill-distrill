# 2_3 (Java 个税计算器 skill) 平台"精确 0"根因研究

- **Query**: 用本地变种复现，钉死 2_3 在平台精确 0 的真因，分清"提取逻辑问题"与"平台环境(超时/崩溃)问题"
- **Scope**: internal（纯代码诊断 + 子进程复现，无网关）
- **Date**: 2026-06-12
- **被测版本**: `source/solution/skills/java_tax_calculator/scripts/run.py` @ HEAD `98b3b4d`（commit "7"，工作区 clean == HEAD）。已含 `_tax_rows_from_lines` / `_parallel_array_tables`（commit 7 引入）与 deadline 自保 `SKILL_BUDGET_SECONDS`（commit `b5be787` 引入）。

> 注：会话开始的 git 快照写 HEAD=`2435424 "6"` 是**过期快照**；`git rev-parse HEAD` 实测为 `98b3b4d "7"`，分析对象即 commit 7。

---

## 0. 基准事实（已逐一实测核实）

| 事实 | 证据 |
|---|---|
| 公开表 = `ded=5000`，brackets 见下，**逐字复现 reference_answer 全 11 段** | 解码 `TAX_BRACKETS_ENCODED`/`DEDUCTION_POINT_ENCODED` + Python 计算 == `question_disc.json` 的 2_3 `reference_answer` |
| 判分 `type=match2`，第 1 段 `contain[21.0.11]`，后 10 段 `is[税额]`，部分分 = 命中段数/11 | `question_disc.json` 2_3 |
| 真题题面（`description`）含 5 条 worked-examples（3000→0.00…100000→27440.00）+ 标准 10 薪资集 | `question_disc.json` 2_3 `description` |
| 真题 `explanation` = "①税率表/速算扣除可变 ②起征点可调 ③错误数量/位置可变 ④输入范围可扩" | `question_disc.json` 2_3 `explanation` |
| `files = ['JavaSource_7_1.java']`（**裸相对名，无目录**） | `question_disc.json` 2_3 `files` |

公开税率表（解码所得，应纳税所得额分段 `[下限,上限,税率,速算扣除]`）：
```
[[0,3000,0.03,0],[3001,12000,0.10,410],[12001,25000,0.20,2660],
 [25001,35000,0.25,4410],[35001,55000,0.30,7160],
 [55001,80000,0.35,15160],[80001,999999999,0.45,15310]]   ded=5000
```
计算式：`taxable=salary-ded`；`taxable<=0 → 0`；按 taxable 落档 `tax=taxable*rate-quick`（`run.py:856-864 calculate_tax`）。

---

## 1. 变种裁决（纯 Python 路径，`config=None`，无网关）

驱动脚本 `research/variants_2_3/drive_variants.py`，对每个变种：手算该变种 ground-truth 10 段 + 自洽 worked-examples → 喂 `extract_parameter_candidates` 与 `try_python_path(None, …)` → 抓实际提交串。**全部实跑通过。**

| 变种 | 形态 | 候选数 | 自校验通过候选 | 走的路径 | 裁决 | 段分 |
|---|---|---|---|---|---|---|
| **V1** | 税率表搬进散文/markdown 注释，删 Base64 | 13 | 1 | `_tax_rows_from_lines`→`_clean_brackets`，examples 验证 | **提取扛住 ✓ VALIDATED** | **11/11** |
| **V2** | 平行数组 `upper/rate/quick`，换档位+换起征点(6000) | 4 | 1 | `_parallel_array_tables`，examples 验证 | **提取扛住 ✓ VALIDATED** | **11/11** |
| **V3** | 保持公开结构+真 Base64 三重编码，只改数值(ded=5500) | 5 | 1 | `decode_parameters` base64 快路，直接验证通过 | **提取扛住 ✓ VALIDATED** | **11/11** |
| **V4** | 二维字面量 `{上限,税率%,速算}`，换值(ded=5000) | 5 | 1 | `_numeric_rows`→`_clean_brackets`(compact 布局)，验证 | **提取扛住 ✓ VALIDATED** | **11/11** |

实测提交串（节选 V2，ded=6000 全新表）：
```
openjdk version "21.0.11",0.00,360.00,2170.00,4300.00,9540.00,10940.00,16860.00,20460.00,45140.00,213140.00
```
与该变种 ground-truth 完全一致。**4/4 变种都拿满 11/11。**

### 1b. 最坏情形：题面 examples 与变种源码表"不一致"（变种改表却仍用公开 examples）
即便如此（`research/variants_2_3/drive_variants.py` 外另测）：
- `try_python_path` 返回 `outputs=None`（所有候选过不了公开 examples），但 `best` 仍是已解码的变种表；
- `answer()` 落 **shape-fallback**（`run.py:990-999`），用 `best` 算并**带上版本段** → 至少 1/11，绝不为 0；
- warnings = `['… do not reproduce the worked examples', 'N source-extracted … did not reproduce …']`。

**结论：在本机可测的纯 Python 提取层，没有任何一种变种形态会导致"精确 0"。** 提取要么全对(11/11)，要么落 shape-fallback(≥1/11 带版本段)。

---

## 2. "精确 0"只可能来自哪里 —— 决定性推理

`match2` 部分分 = 命中段数/11。**只要 skill 吐出任何带 `version` 段的 11 段答案，第 1 段 `contain[21.0.11]` 必命中 → ≥0.8/11 ≈ 0.27/3，不可能是 0。** 故"精确 0"的**充要条件 = 提交给判分器的答案里连版本段都没有**，即 **skill 的 stdout 根本没到判分器，最终答案由 router 的 model loop 产出（无版本前缀）**。

### 2.1 stdout 被丢弃的唯一机制（已实测）
`skill_runtime.py:161-174`：
```python
completed = subprocess.run([... run.py], timeout=480, ...)   # 行161-170
if completed.returncode != 0:                                 # 行171
    raise RuntimeError(... )                                  # 行172-173  ← stdout 被丢
return completed.stdout.strip()                               # 行174（仅 rc==0 才返回）
```
- run.py `main()`（`run.py:1009-1018`）：顶层异常 → `_emit({"error":…})` 后 **`raise SystemExit(1)`** → returncode 1。
- returncode≠0 → `run_skill` 抛 RuntimeError，**stdout（含 `{"error":…}` 或任何答案）被丢**。
- router `_try_explicit_skill_route`（`contestant_agent.py:124-133`）catch 该异常 → 打印 stderr → **`return None`** → 落 model loop。
- model loop 在此 grader 上几乎不会自带 `openjdk version "…"` 前缀 → **精确 0**。

实测两种 returncode（子进程复现）：
- 源文件找不到 → stdout=`{"error":"Java source file not found"}`，**returncode=1**（`run.py:118` 抛 → `main` 兜底 → SystemExit(1)）。
- 正常 → stdout=`{"answer":"openjdk version \"21.0.11\",…", "path":"python", …}`，**returncode=0**。

### 2.2 但"超时被 kill"在默认 env 下几乎不可能（已实测算账）
- `skill.json timeout_seconds=480` 是唯一墙钟（无每题时限，仅 1h 总限）。
- run.py 默认：`AGENT_DEMO_TIMEOUT_SECONDS=60`→`timeout=60`；`extract_timeout=repair_timeout=min(timeout,20)=20`；`max_rounds=1`。**即便把 `AGENT_DEMO_TIMEOUT_SECONDS` 调到 600，因 `min(,20)` 兜底，单次模型 timeout 仍 ≤20s**（`run.py:957-958`）。
- 最坏阻塞（提取空 + 网关每次卡满 + 各 retry 一次 + javac 20s）≈ `2*20+1.5 + 2*20+1.5 + 20 ≈ 103s` ≪ 480s。
- deadline 自保（`run.py:46-49,924-929,422-429`）：`remaining<30s` 跳过 py 提取调用、`<35s` 跳过 java 修复轮 —— 时间将尽时是**跳过而非启动**，**emit 永远到得了**。
- 实测：强制 config 在场 + 模型调用全失败 + 无 javac → `answer()` **0.00s 返回** `openjdk version "21.0.11",0.00,0.00`（带版本段），`path=unverified`。

**→ 只要 run.py 这个进程能正常 return，`answer()` 必吐带版本段的 11 段；超时-kill 这条路在默认 env 下基本被堵死。**

### 2.3 端到端复现（平台式 `_runtime` 注入 + 相对 source_file）
`mcp_client.py:102-133 _inject_skill_runtime` 会把 `question_dir` + `allowed_file_paths`(绝对) 注入 `arguments._runtime`；`resolve_source_file`（`run.py:110-118`）据此解析相对名 `JavaSource_7_1.java`。子进程实测：**returncode=0，`path=python`，输出 == reference_answer 全 11 段**。本仓库自带 runtime 下 happy path 完全正确。

---

## 3. 决定性结论：平台"精确 0"最符合哪种？

**排除 (A) 提取逻辑在变种上失败**：4 种变种形态全部 11/11；最坏 examples-不一致也只落到 ≥1/11 的 shape-fallback。本机可测范围内，提取层**不是**病根。

**指向 (B) skill 进程未吐答案（returncode≠0 → stdout 被丢 → model loop → 无版本段 → 0）**。这是唯一能产生"精确 0"的机制（§2.1 引用 `skill_runtime.py:171-173`、`contestant_agent.py:131`、`run.py:1017`）。但在**本仓库 runtime + 默认 env** 下，我无法让它自然发生（超时被自保堵死、源解析被 `_runtime` 注入解决）。因此 returncode≠0 的实际触发点**只能在"本仓库 runtime 与平台真实执行环境的差异"里**，最可能的三条（按概率）：

1. **平台未注入 `_runtime`（或字段名/结构不同）⇒ 相对名 `JavaSource_7_1.java` 解析失败 ⇒ `FileNotFoundError`（`run.py:118`）⇒ SystemExit(1) ⇒ 0。**
   - 风险点：router 只传 `source_file="JavaSource_7_1.java"`（裸相对名，`contestant_agent.py:401-403`），skill 子进程 `cwd=skill_dir`（`skill_runtime.py:166`）。若平台 MCP 层不像本仓库 `_inject_skill_runtime` 那样回填 `_runtime`，且不把声明文件 stage 进 cwd，则 `_candidate_paths`（`run.py:98-107`）三个候选(question_dir 空 / cwd=skill_dir / 裸名)全落空，`allowed_file_paths` 也空 → 抛错归零。**这是头号嫌疑，且与"连续多次精确 0、与表内容无关"高度吻合。**
2. **平台对 skill 子进程的真实墙钟 < 480s，或 `SKILL_BUDGET_SECONDS` 未注入/被改小，叠加 thinking 默认状态/网关抖动**，使 `subprocess.run(timeout=…)` 真的触发 `TimeoutExpired`（kill），stdout 被丢。本机算账显示默认 env 下不该发生，但若平台 env 与假设不同则可能。
3. **router 在平台上根本没路由到该 skill**（`has("java_tax_calculator")` 为假——平台可见 skill 集合不同，或题面字段映射差异致 `question_text` 为空且 `files` 未带 `.java`）→ 纯 model loop → 0。本仓库 `public_question_fields:44` 已把 `description→question`、`_explicit_skill_route:396-404` 命中 `.java`，但平台打包/字段可能不同。

**(C) 其它（答案段数错乱 / 版本不匹配）基本排除**：`answer()` 恒拼 `[version]+10` = 11 段（`run.py:1002`）；版本段是硬编码 `openjdk version "21.0.11"`（`run.py:39,289-291`，`JAVA_VERSION_USE_SYSTEM` 默认 false 不调真 `java -version`），`contain[21.0.11]` 必命中。段数/版本不会致 0。

> 一句话：**提取逻辑已被证伪为病根；"精确 0"的机制锁定为 returncode≠0 → stdout 被丢 → 落 model loop（无版本段）。其最可能的实际触发不在 skill 算法里，而在"平台运行环境是否注入 `_runtime`/是否 stage 声明文件/真实墙钟与 env"。** 当前代码无法在本机自然复现该归零，说明问题在本机不可见的执行环境差异面。

---

## 4. "javac 编译为主路径"该不该上？——会更糟

**结论：不要把 javac 设为主路径；维持"Python 提取优先、javac 仅 fallback"。** 理由（代码层推理，本机无 Java 不能实测）：

1. **更吃时间、更易踩 §2.1 的归零雷**。javac 路径（`run.py:403-472 try_java_path`）= LLM 修复(≤20s,可 retry) + `javac`(20s 超时) + 每条 worked-example `run_java_case`(5s) + 每条隐藏用例 `run_java_case`(5s×10)。最坏轮次叠加远超纯提取的 ~103s，越靠近 480s 墙越可能 `TimeoutExpired`→kill→stdout 丢→**精确 0**。纯提取几乎不耗墙钟，emit 稳。
2. **公开源码 bug 密度高，单轮修复成功率存疑**：`JavaSource_7_1.java` 至少 7 处错（`args[1]` 应 `args[0]`；`salary + deductionPoint` 应 `-`；`if(taxableIncome>=0)return 0` 反了；`sout(...)` 非真方法；`Base64` 未 import；`calculateTax` 非 static 却被 static main 调用；`for i<=length` 越界；档位取 `[i][1]/[i][0]` 列错、`+deduction` 应 `-`）。`max_rounds=1`（`run.py:959`）下一轮编译+示例全过的概率不稳，失败即回退——白烧时间。
3. **方向与病根相反**：若病根是 §3-(1)/(3)（环境/路由/源解析），javac 主路径一点不治本，反而把"稳吐 shape-fallback"的纯 Python 兜底挤到时间后段，增加 kill 概率。**javac 是净负**。

唯一价值：javac 能在"提取彻底失败且时间充裕"时作为兜底救少数极端变种——保持现状（fallback）即可，不前移。

---

## 5. 给 2_3 的具体修法（按 ROI 排序）

> 这些是研究结论指向的修改方向，供主 agent 决策；本研究**未改任何 skill 源码**。

1. **【最高 ROI，直接堵精确 0】让 skill 子进程"永不以非 0 退出"，把 stdout 落地。** 预期：把"精确 0"系统性抬到 **≥0.8/11≈0.27/3（版本段保底）**，正常变种 →满分 3/3。两处协同：
   - **run.py `main()`**：异常分支也要 emit 一个**合法 11 段 shape**（版本段 + `0.00`×N）后**以 returncode 0 退出**（不要 `raise SystemExit(1)`）。即"无论如何先吐带版本段的答案，再正常退出"。
   - **skill_runtime.py:171-174**：returncode≠0 时**不要丢 stdout**；若 stdout 是合法 JSON(含 `answer`)就返回它，仅在 stdout 空时才报错。（双保险，防任何子进程异常退出归零。）
   - 段分收益：版本段 1/11 保底；若 fallback 用已解码表，常拿 11/11。

2. **【次高 ROI，治 §3-(1) 源解析】source_file 解析更稳健 + 自带兜底。** 预期：若病根是相对名解析失败，单此一项即从 0 → 满分（变种提取已证扛得住）。
   - router 侧（`contestant_agent.py:401-403`）：尽量传**绝对路径**（用 `allowed_file_paths` 里 `.java` 的绝对名），不要只传裸相对名。
   - skill 侧（`run.py:110-118 resolve_source_file`）：在现有候选基础上，**优先无条件扫 `_runtime.allowed_file_paths` 里的 `.java`**（已有该兜底在 line 115-117，但置于裸名候选之后；可前置），并对 `task_description` 里若内联了源码/表也能直接解析。
   - 段分收益：解析成功后纯 Python 路径 = 11/11。

3. **【中 ROI，防 §3-(2) 超时-kill】缩短墙钟暴露面。** 预期：进一步把"被 kill 归零"概率压到 ~0。
   - 维持 Python 提取优先、javac 仅 fallback（§4），**不前移 javac**。
   - 可把 `EMIT_MARGIN_SECONDS`（`run.py:47`）从 20 调大到 30-40，并确认平台真实 `SKILL_BUDGET_SECONDS` 注入值；让 emit 余量更宽。
   - 段分收益：保住 §1 已能拿的 11/11 不被墙钟吃掉。

4. **【低 ROI，提鲁棒性】提取覆盖再扩。** 预期：边际段分，主要防"罕见表达式变种"。
   - 现有 `_tax_rows_from_lines`/`_parallel_array_tables`/`_numeric_rows` 已覆盖散文/markdown/平行数组/二维字面量四类（§1 全过）。可再补：税率写成小数(0.03)而非百分比的注释行、全角符号、表头行干扰等。
   - 段分收益：仅对当前四类之外的变种有用；优先级最低。

**首选执行顺序：先做 1（永不非 0 退出 + stdout 落地）+ 2（source 解析兜底），这两项直接对应"精确 0"的唯一机制与头号触发点；3 防守超时；4 锦上添花。**

---

## Files Found / 关键引用

| 路径 | 作用 / 关键行 |
|---|---|
| `source/solution/skills/java_tax_calculator/scripts/run.py` | skill 主体。`calculate_tax:856`、`extract_parameter_candidates:779`、`_tax_rows_from_lines:545`、`_parallel_array_tables:601`、`try_python_path:876`、`answer:947`、shape-fallback:`990-999`、deadline 自保:`46-49/924-929`、`main` 异常→SystemExit(1):`1009-1018`、版本段硬编码:`39/289-291` |
| `source/runtime/skill_runtime.py` | `run_skill:142-174`，**returncode≠0 丢 stdout 抛错:171-173**，注入 `SKILL_BUDGET_SECONDS=timeout_seconds:160` |
| `source/solution/contestant_agent.py` | 路由 `_explicit_skill_route:396-404`（传裸相对 source_file）、skill 失败 catch→None:`124-133`、`_guard_java_tax_calculator:254-263`（要求 ≥11 段 + 版本段） |
| `source/runtime/mcp_client.py` | `_inject_skill_runtime:102-133`（注入 `_runtime`=question_dir+allowed_file_paths，**平台是否等价存疑**） |
| `source/runtime/question_schema.py` | `public_question_fields:44`（`description→question`，本仓库下 task_description 非空） |
| `publish/publish_V1/question_disc.json` | 2_3 `reference_answer`/`description`/`explanation`/`files`/`type=match2` |
| `publish/publish_V1/JavaSource_7_1.java` | 公开半成品源码（≥7 处 bug，javac 路径须全修） |
| `source/eval/tests/test_java_tax_calculator.py` | 既有离线测试：已覆盖 base64 改名/内联百分比表/markdown 注释/平行数组四类（全绿） |
| `.trellis/.../research/variants_2_3/V1..V4_*.java` | 本研究造的 4 个扰动变种源码 |
| `.trellis/.../research/variants_2_3/drive_variants.py` | 纯 Python 无网关驱动，复现 §1 全部裁决 |

## Caveats / Not Found

- **本机无 Java（javac/java 不可用）**：javac 修复路径只做了代码层推理，未实测其墙钟/成功率（§4）。
- **平台真实执行环境不可见**：是否注入 `_runtime`、是否 stage 声明文件进 cwd、真实 `SKILL_BUDGET_SECONDS`/thinking 状态/网关延迟，均无法在本机验证。§3 的 (1)(2)(3) 三条触发点是基于"本机可测范围内提取/超时/happy-path 全部正常 ⇒ 病根必在环境差异面"的反推，需在环境机上抓 skill 子进程的真实 returncode/stderr/stdout 才能最终钉死是哪一条。
- 子进程复现里两次出现 returncode=2，均为**测试命令把相对 run.py 路径与 `cwd=skill_dir` 叠加导致路径翻倍**的测试脚本瑕疵，**非 skill 缺陷**；改用绝对 run.py 路径后即 returncode=0 正常（§2.3 实测）。
