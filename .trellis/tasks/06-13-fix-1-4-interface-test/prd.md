# PRD — 修复 1_4 接口测试题平台塌分（1.49/6）

## 背景 / 症状
- 题 1_4「接口测试结果识别」：判分 `type=ratio`、`score=2`（平台×3 → 满分 6）。
  判分逐位置比较逗号分段（`source/eval/score.py:score_ratio`）：**任何早位偏差（错报/多报/早位漏报）会把后续全部归零；只有缺尾巴才温和衰减。**
- 返回格式要求（题面）：**仅返回失败用例 ID，多个 ID 按测试用例顺序用英文逗号分隔，不要输出解释**。样例 `TC000,TC999`。参考答案 `TC009,TC011,TC014,TC015,TC016,TC020`。
- 赛方反馈：「你的 1_4 返回要按照题目要求来，你这个不对应」；本轮该题得分 **1.49/6**。
- 日志：`solve start id='1_4' … explicit route='interface_test'`（路由正确）；平台 10 题**并发**执行（多线程）。

## 本地取证（决定性）
| 场景 | answer | 平台分(×3) |
|---|---|---|
| 公开集 纯代码(config=None) | `TC009,TC011,TC014,TC015,TC016,TC020` | **6.0/6** ✅ |
| 变种 reworded 纯代码 | `TC009,TC011,TC014,TC015,TC020`（弃权 TC016，**保住正确前缀**） | 4.0/6 |
| 变种 reworded **+模型(DashScope 35B)** | 精确参考 | **6.0/6** ✅ |
| 变种 aggressive 纯代码 | 精确参考 | 6.0/6 ✅ |
| **平台实跑** | ？（未见于日志） | **1.49/6** ⚠️ |

结论：skill **核心算法与 `_extract_skill_answer` 都没问题**；本地所有路径都拿 4–6/6，**比平台的 1.49 还高**。平台塌分发生在**编排层**。

## 根因（编排层，两连环）
1. **丢弃高置信前缀**：平台并发 → 共享模型网关受压 → 1_4 逐用例的模型调用大量超时/报错 → 弃权用例（judged=False）占比 >1/3 → `run.py answer()` 命中 `unjudged*3 > len(cases)` **抛 RuntimeError**，把已判出的"正确失败 ID 前缀"整个丢掉。
2. **回退后无格式守卫**：`_try_explicit_skill_route` 捕获异常返回 None → `solve()` 落 model loop。而 `interface_test` 是**唯一没有 `_guard_*` 方法**、且在 `_EMPTY_ANSWER_OK` 的路由 skill → 模型自由文本（解释 / 顿号分隔 / 多行）**原样提交** → 赛方看到「格式不对应」，`score_ratio` 逐位置错位 → 低分。

> 病根 = 编排层（丢答案 / 回退无守卫），不是接口调用或断言算法。与历史教训一致：**精确/异常低分先查编排层**。

## 修复方案（均为定点修，net-positive，低风险）

### FIX 1 — `run.py answer()`：有高置信失败就别抛异常丢前缀
`unjudged*3 > len(cases)` 的 raise 只应在**没有任何已确认失败**（会提交无意义的 all-pass）时触发。
改：`if cases and config is not None and not failed and unjudged*3 > len(cases): raise …`。
有 `failed` 时直接返回**保守正确前缀**（逐位置 grader 下前缀永远拿分、不可能被归零），严格优于回退到无守卫 model loop 的赌博。符合该 raise 的原始意图（逃离 all-pass）。

### FIX 2 — `contestant_agent.py`：补 `interface_test` 的格式守卫 + 打捞
- 新增 `_guard_interface_test`：拒绝多行 / 超长 / 任一分段非 ID 形状（`[A-Za-z][A-Za-z0-9_-]*`）的答案 → 触发 strict retry（要 bare IDs）。空答案合法（"无失败用例"）继续由 `_EMPTY_ANSWER_OK` 处理。
- 新增 `_normalize_interface_test_answer`：model-loop 回退答案在守卫前先**打捞**——已是干净逗号 ID 列表则原样返回；否则按主导前缀提取 ID token 逗号拼接（prose/顿号/多行 → 合规 ID 串；无 ID → 空=无失败）。保证**任何路径**都满足"仅 ID、逗号分隔"。
- 在 `solve()` 进入 `_guarded_model_answer` 前，对 `routed_skill=="interface_test"` 先 normalize。

## 不做（避免过度工程 / 投机）
- 不改 skill 内逐用例模型置信逻辑（本地模型 6/6 不过报；改动投机且有回归风险）。
- 不整体重写 skill（公开集满分路径必须保留）。

## 验收
1. **零回归**：`python -m pytest source/eval/tests`（或现有 runner）全绿。
2. 公开集纯代码仍 `TC009,TC011,TC014,TC015,TC016,TC020`（6/6）。
3. 本地变种纯代码/含模型 ≥ 现状（reworded 纯代码 4/6、含模型 6/6；aggressive 6/6）。
4. 新增单测：`_guard_interface_test` 接受干净 ID 串、拒绝 prose/多行；`_normalize_interface_test_answer` 把顿号/prose 打捞成合规串；FIX 1 在「有 failed + 高弃权」时返回前缀不抛异常、在「无 failed + 高弃权」时仍抛异常回退。
5. 探针重交：`AGENT_DEMO_ONLY_QUESTION_IDS=1_4`（收官前再全量）。
