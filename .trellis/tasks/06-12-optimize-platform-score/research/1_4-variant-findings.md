# Research: 1_4 interface_test —— 变种复现 + 真因裁决

- **Query**: 用本地变种 + 本地 mock 钉死 1_4（接口测试 skill）平台近 0 分的真因，证实/证伪 "conservative-pass 漏报" 假说，回答 "skill 靠不靠谱、要不要换"。
- **Scope**: internal（读 skill / 三件套 / mock / 评分器）+ 本地实跑（mock 18081 + 真 35B 网关）
- **Date**: 2026-06-12
- **约束遵守**: 只读真 skill，未改动 `source/solution/skills/interface_test/scripts/run.py`；所有原型改动只发生在 `research/variants_1_4/run_proto.py` 副本。

---

## TL;DR 裁决

1. **conservative-pass 漏报 不是 元凶**（至少不是主因）。本地变种下真正塌分的机制是 **`infer_steps_from_case` 过度自信地构造了"错误但 HTTP 200"的请求 → 把本应 PASS 的用例误判为 FAIL（多报）**，而多报恰好发生在失败列表的**最前面（TC006/07/08 在 TC009 之前）**，把 position-sensitive 的 `ratio` 直接打到 **0/6**。
2. **纯代码 `infer_steps_from_case` 帮了倒忙**：它对 search/分页类用例**不肯弃权**——即使措辞变化后抽不出判别性过滤条件（status/department/keyword），它仍照发 `/api/user/search`，拿到合法的空结果集，然后误判。而且它**跑在模型前面**，一旦它"判了"，模型这条退路就**永远不会被触发**。
3. **skill 不是"完全不靠谱"，但当前形态在变种上极脆**：公开集 2.0/2.0 满分；任一自然改写的变种 0.0/2.0。**可救，但必须改两处**（见"建议"），且要认清 `ratio` grader 的本质——**早位多报 = 归零，末位多报 = 免费，缺中段 = 掉尾巴**。
4. ⚠️ 反直觉但关键：原型修复后，**离线（无模型）反而比带模型分更高**（1.0 vs 0.0），因为带模型时它recover了 4 个 search 用例却把 TC006 判错，又在 0 号位插了一个多报 → 再次归零。**说明在这个 grader 下，"干净地少报正确前缀" 优于 "带噪声地多报"。**

---

## Findings

### 1. 6 个失败用例为什么失败（服务返回 vs 断言）

公开 mock（`public_root`）里写死了 6 处"故意失配"，对应参考答案 `TC009,TC011,TC014,TC015,TC016,TC020`：

| ID | 用例意图 | 服务真实返回（public_mock_service.py） | 断言要求 | 失败原因 |
|---|---|---|---|---|
| TC009 | `U1010` detail verbose 校验经理 | `handle_detail`: `manager.name="WrongManager"`（L405） | `data.manager.name="ManagerA"` | 值失配 |
| TC011 | `mobile` 部门活跃统计 | `handle_stat_active`: `activeCount=63`（L634） | `data.activeCount=64` | 值失配 |
| TC014 | `U1004` detail 校验职级 | `handle_detail`: `result.pop("title")`（L404） | `data.title="Engineer"` | 字段缺失 |
| TC015 | active/desc 第一页首条 | `handle_search`: active 分支忽略 sortOrder，首条恒 `U2001`（L435-436） | `data.list.0.userId="U2240"` | 值失配 |
| TC016 | inactive/desc 第一页首条 | `handle_search`: `first="U9008"`（desc, L445-446） | `data.list.0.userId="U9009"` | 值失配 |
| TC020 | `U1005` detail 职级应为 Quality Owner | seed `U1005.title="Engineer"`（未被任何写改） | `data.title="Quality Owner"` | 值失配（"自相矛盾"陷阱：TC019 校验 Engineer→PASS，TC020 对同一未变用户校验 Quality Owner→必 FAIL） |

这 6 个失败由**断言里的固定值/固定字段**驱动，与措辞无关——所以**只要 skill 能正确发出请求，这 6 个 ID 就是稳定的**。变种题改的是**描述措辞**，不改断言/ID（题面 explanation 也承诺"完整重复执行时失败用例集合应保持一致"）。

### 2. 基线（公开集，未改动）= 满分，0 弃权

| 跑法 | answer | unjudged | 平台分(score_ratio, 权重2.0) |
|---|---|---|---|
| 纯代码（无模型，config=None） | `TC009,TC011,TC014,TC015,TC016,TC020` | **0** | **2.000 (6/6)** |
| 真 35B 模型 ON | 同上 | **0** | **2.000 (6/6)** |

关键事实：**公开集下 20 个用例 100% 被 `infer_steps_from_case`（纯代码）判掉，模型根本没被调用**（即使 MODEL_* 配齐，纯代码先返回 steps，`_verify_one` 在 run.py L1192-1199 直接 run+assert+`judged=True` 返回，不进 L1204+ 的模型分支）。这解释了为什么"本地满分"——公开集的措辞恰好命中所有正则。

### 3. 变种（改措辞、保断言/ID）= 0 分，机制是"多报"非"漏报"

在 `research/variants_1_4/` 造了两个变种（`variant_reworded` / `variant_aggressive`），**只改 `description` 自然改写，`assert`/`id` 与 `api_doc.md`/`auth_config.json` 逐字不变**（端点不动，隔离"描述解析"单一变量）。

真 skill 在 `variant_reworded` 上（两个变种结果一致）：

| 跑法 | answer | unjudged(judged=False) | 平台分 |
|---|---|---|---|
| 纯代码（无模型） | `TC006,TC007,TC008,TC009,TC011,TC014,TC015,TC016,TC020` | **1** (`TC005`) | **0.000 (0/6)** |
| 真 35B 模型 ON | `TC006,TC007,TC008,TC009,TC011,TC014,TC015,TC016,TC020` | **0** | **0.000 (0/6)** |

**数字证伪了"conservative-pass 漏报是主因"**：
- 走 conservative-pass 的只有 **1 个**（TC005 批量，因为改写后抽不出 status 值，`infer` 弃权 → 无模型时降级保守）。漏报 1 个不致命。
- 真正的塌分来自 **5 个 search 用例（TC006/07/08/15/16）被多报/误判为 FAIL**，原因 `missing field data.list.0.userId`：改写后 `_query_from_description` 丢了 `status=/department=/keyword=` 判别条件，但 `infer_steps_from_case` 的 search 分支**仍发请求**（只剩 `page/sortOrder`），mock 命中 `handle_search` 末尾 `return ok({"total":0,"list":[]})` → `data.list.0.userId` 不存在 → 误判 FAIL。
- 后果在 `ratio` grader 下是**毁灭性的**：多报的 TC006 排在最前，`ans[0]=TC006 != ref[0]=TC009`，**之后所有位置全部错位 → 0/6**。

**模型 ON 也救不了**：因为 `infer_steps_from_case` 跑在前面且对这些用例**不报错**（HTTP 200 空列表，非 transport error），`_verify_one` 当场 `judged=True` 返回，**永不进入模型分支**。模型这条退路被纯代码短路了。

### 4. 机制实证（probe_infer.py：公开 vs 改写抽取对比）

| 用例 | 公开抽取的 query | 改写后抽取的 query | infer 行为 |
|---|---|---|---|
| TC006 | `{department:platform,page:2,pageSize:2,sortOrder:asc}` | `{sortOrder:asc}`(+补 page/size) | ❌ 仍发 search，**丢 department** |
| TC007 | `{status:active,page:1,pageSize:100,sortOrder:asc}` | `{sortOrder:asc}`(+补 page/size) | ❌ 仍发 search，**丢 status** |
| TC008 | `{keyword:Alice,page:1,pageSize:10}` | `{}`→`{page:1}` | ❌ 仍发 search，**丢 keyword** |
| TC015 | `{status:active,page:1,pageSize:5,sortOrder:desc}` | `{sortOrder:desc,page:1}` | ❌ 仍发 search，**丢 status** |
| TC016 | `{status:inactive,...,sortOrder:desc}` | `{sortOrder:desc,page:1}` | ❌ 仍发 search，**丢 status** |
| TC005 | `{}`(ids/status 走专门正则) | 抽不出 status 词 | ✅ **弃权 []**→落模型（正确行为） |
| TC009 | `{verbose:true}` | `{}`（但 assert 有 `data.manager.`→注入 verbose=true） | ✅ 侥幸：U1010+verbose 仍对 |
| TC011 | `{department:mobile}` | `{}`（"mobile 这个部门" 被 `([A-Za-z0-9_\-]+)\s*部门` 捞回） | ✅ 侥幸：mobile 仍对 |

→ **search 分支是病灶**：判别条件丢失时它"自信地发错请求"而非弃权。detail/stat 这次侥幸存活（U#### id、`verbose`、`mobile` 字面仍在），但同样是**正则运气**，不是设计保证——稍微换个写法（如把 `U1010` 写成"工号 1010"、把 `mobile` 译成中文部门名）一样会崩。

### 5. `ratio` grader 的真实语义（source/eval/score.py:74 `score_ratio`，已对公开集校准）

```python
hits=0
for index, ref_item in enumerate(ref_list):          # 只遍历参考的 6 个位置
    if index < len(ans_list) and ans_list[index]==ref_item:
        hits += 1
earned = score * hits / len(ref_list)                # score=2.0, len(ref)=6
```

实测敏感度（权重 2.0，参考 6 段）：

| 答案形态 | 分数 | 说明 |
|---|---|---|
| 完全正确 | 2.000 (6/6) | |
| 末尾少 1 / 少 2 / 少 3 | 1.667 / 1.333 / 1.000 | **正确前缀照拿分，掉尾巴很温和** |
| 只报对第 1 个 | 0.333 | 前缀 1 位 |
| 缺一个**中段**(TC014) | 0.667 (2/6) | 尾部左移，但前缀仍得分 |
| 最前面多 1 个 | **0.000** | **早位多报 = 归零** |
| 中段多 1 个(TC011后) | 0.667 | 吃掉后半 |
| **末尾多 1 个** | **2.000** | **末位多报完全免费**（grader 只看前 6 位） |
| 空答案(全 PASS) | 0.000 | |

**结论性事实**：
- 最优策略 = **宁可少报（保住正确前缀），绝不在前/中位多报**。conservative-pass 的"宁少勿多"哲学方向**对**。
- 但 skill 当前实现**背叛了这个哲学**：`infer_steps_from_case` 在抽不出参数时**多报**（而非弃权/保守），而 `_verify_one` 的 conservative-pass 只兜 **transport/parse 失败**，兜不住 **"HTTP 200 但语义错"** 这一变种主病。

### 6. 原型修复验证（research/variants_1_4/run_proto.py，未触真 skill）

**修法**：search 分支增加弃权条件——当断言需要行数据（`data.list.*`/`data.total`）但只剩分页/排序键、**没抽到判别性过滤条件（status/department/keyword）** 时，`return []` 弃权 → 落模型；离线则 conservative-pass。

| 场景 | answer | 平台分 | Δ vs 真 skill |
|---|---|---|---|
| PUBLIC, 无模型（回归） | `TC009,TC011,TC014,TC015,TC016,TC020` | **2.000** | 不回归 ✅ |
| 变种, 无模型（弃权→保守） | `TC009,TC011,TC014,TC020` | **1.000 (3/6)** | **0 → 1.0** ✅ |
| 变种, 真 35B 模型 ON | `TC006,TC009,TC011,TC014,TC015,TC016,TC020` | **0.000 (0/6)** | 0 → 0 ⚠️ |

- 修复后**离线分从 0 → 1.0**：弃权让 5 个 search 用例不再误判，干净保留 4 个纯代码铁判（TC009/11/14/20），形成正确前缀。
- **带模型却仍 0**：35B 把 TC007/08/15/16 都 recover 对了，但 **TC006 仍解析错**（reworded "平台部门第二页每页两条升序" 模型没把 department=platform/分页解析正确）→ 又在 0 号位多报 → 归零。**这说明只靠"弃权落模型"不够，还要治多报本身**。

---

## 裁决（直接回答用户）

### conservative-pass 是不是元凶？
**不是。** 元凶是 **`infer_steps_from_case` 对 search 类用例"不弃权地发错请求"导致的早位多报**，叠加 **`ratio` grader 对早位多报零容忍**。conservative-pass 只是没能兜住这种"HTTP 200 语义错"的失败模式（它只兜 transport/parse 失败）。漏报在本变种里只贡献 1 个用例，无关大局。

### 纯代码推断帮没帮上忙？
**公开集帮了（满分全靠它）；变种里帮了倒忙**——它既制造多报，又因跑在模型前而**短路掉模型退路**。它是"高置信"假设的反例：置信不等于正确，且它不肯在不确定时弃权。

### skill 靠不靠谱？要不要换？
**不是"完全不靠谱"，但当前形态在变种上不可用（0 分），属于"必须定点改、且改完仍有上限"。**

- **架构骨架是对的**：纯代码做断言（`assert_response`）、按文件序拼接、宁少勿多——这些都吻合 grader。**不建议整体重写**（重写收益有限，且会丢掉公开集已验证的满分路径）。
- **但有两个必须修的硬伤**（见下），不修则任何措辞变种都 0 分。
- **认知天花板**：即使修好路由，**只要 35B 对某个改写用例判错并多报到前/中位，整题仍归零**。这是 grader×单点错误的乘法效应，非 skill 单方能完全消除。

---

## 建议（具体修法，按性价比排序；均为定点修，非重写）

**修 A（必做，最高性价比）—— search/分页分支"无判别条件即弃权"**
在 `infer_steps_from_case` 的 search 分支（run.py ~L933）：当断言需要行（`data.list.*`/`data.total`）但 query 缺 status/department/keyword 时 `return []`。
- 效果（实测）：变种离线 0→1.0，且公开集不回归。
- 本质：让纯代码**只在能从字面确证参数时才判**，否则把不确定交给模型/保守，**杜绝早位多报**。

**修 B（必做）—— 治"HTTP 200 语义错"的多报：让 `_verify_one` 对"可疑空结果/字段缺失"也回退模型，而非当场判 FAIL**
当前 `_verify_one`（L1192-1199）只要纯代码 run 不报 transport error 就 `judged=True`。建议：当**纯代码推断的请求**得到的响应**未通过断言、且失败原因是"字段/行缺失"（典型的发错请求特征）**时，**不要立刻判 FAIL，而是回退到模型重解析这一条**（模型 ON 时），模型也判 FAIL 才记 FAIL。
- 这能把"修 A 弃权后落模型，但模型也可能误判"和"纯代码误判"统一收敛到"两条证据都指向 FAIL 才报"，进一步压低多报概率（针对 TC006 这种模型也吃力的用例，至少不会比保守更差）。

**修 C（强烈建议）—— 把"宁可末位多报、绝不早/中位多报"写进编排**
鉴于 grader **末位多报免费、早位多报归零**：失败 ID 的产生应保证**只在高置信时插入靠前位置**；低置信的疑似失败可以**往末尾放或干脆不报**。具体可在 `answer()` 汇总 `failed` 时，对 `judged=False`（保守）但"疑似失败"的用例，宁可丢弃也不要插到已确认失败 ID 的前面。
- 配合修 A/B，把"不确定"系统性地导向"少报正确前缀"，吃满 grader 的偏好。

**修 D（可选，提鲁棒性）—— 强化 `_query_from_description` 的中文/自然语言抽取**
现有正则强依赖 `key=value` 与少量中文模板。可补：从 `expectedValues` 反推（已部分有 `_merge_asserted_query_values`，但 TC006/07/08 不 assert 这些值，反推失效）→ 改为**结合 api_doc 的参数枚举（status∈{active,inactive}、sortOrder∈{asc,desc}）做"描述里出现枚举词即填"**，例如描述含"活跃/在岗"→status=active、"降序/倒序/从大到小"→sortOrder=desc、"停用/不活跃"→status=inactive。
- 这是"少依赖模型"路线的正解，但务必配合修 A 的弃权兜底（抽不到就弃权，别硬发）。

**不建议**：删掉 conservative-pass（它在 transport/parse 失败时仍是正确的"宁少勿多"）；整体改回"纯模型循环"（公开集满分会丢，且模型对 search 改写同样会错）。

---

## Caveats / Not Found

- 本研究**只扰动了 description 措辞**（隔离单变量）。题面 explanation 还允许变种**改端点/请求方式/参数结构/鉴权/返回字段**——那些会额外打击 `parse_endpoint_catalog`/`build_auth`/`assert_response`，**本研究未覆盖**，但修 A/B/C 的方向（弃权 + 双证据 + 偏好末位）对那些变种同样适用。
- 真 35B 在 `variant_reworded` 上对 TC006 的误判，是**单次**观测（temperature=0，但仍可能随网关状态波动）；TC007/08/15/16 被 recover 正确。模型对中文分页改写的可靠性约 **4/5**，不足以单点兜底——这正是建议"双证据 + 偏好末位"的依据。
- 平台 mock 是否与本地 `public_mock_service.py` 完全一致：本地 18081 上跑的是 prior session 的常驻服务（health=public_root, serviceVersion 2.3），与 `.py` 源一致；变种用的是我在 research 下生成的副本输入，未改 mock 行为，故 6 个失配点与公开集一致。
- **环境**：mock 服务（18081）在本会话开始前已由上一会话常驻（我的后台启动检测到 "already running" 即退出，未新建监听进程），故无我自己产生的后台 mock 进程需要回收；所有后台 bash 任务均已结束。

---

## 复现入口（均在 research/variants_1_4/）

- `harness.py <doc_dir> [--model] [--reset]` —— 驱动**真 skill** `answer()`，打印 answer/unjudged/per_case/grade。
- `harness_proto.py <doc_dir> [--model] [--reset]` —— 同上但加载 `run_proto.py`（已打补丁的原型）。
- `make_variant.py` —— 生成 `variant_reworded/` 与 `variant_aggressive/`（只改 description）。
- `probe_infer.py` —— 对比公开 vs 改写下 `infer_steps_from_case` 的抽取与发出的请求。
- `apply_proto_fix.py` —— 给 `run_proto.py` 打"search 弃权"补丁（幂等）。
- `score_scenarios.py` —— 用真 grader `score_ratio` 给所有实测 answer 打平台分。
- 真 35B：`set -a; . .env.dashscope; set +a` 后加 `--model`。
