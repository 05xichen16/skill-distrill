# Research: 判分语义 (ratio / list_equal) 精确语义

- **Query**: 1_4 判分 type=ratio、3_3 判分 type=list_equal 的确切实现与对答案格式的硬约束
- **Scope**: internal
- **Date**: 2026-06-11

## 来源

- 离线判分器 `source/eval/score.py`（复刻平台判分语义，已对公开答案 key 校准；模块头部注释 `source/eval/score.py:1-26` 声明锚点 1_1=2.0 / 1_3=2.0 / 3_2=5.0、总分 12.386/32 精确复现）。
- 平台答案 key：`publish/publish_V1/question_disc.json`（每题含 `id` / `type` / `score` / `reference_answer`）。
- 实际打分入口 `score_results` 见 `source/eval/score.py:157-194`：按 `disc_list` 逐题取 `reference_answer` 与本题 `answer`，`earned = score_one(type, ref, ans, score)`。

注意：**两种类型都是“按比例给分”**，不是 0/1。错一部分只扣对应比例。评分次序为 正确性 >> token >> 提交次数，所以正确率每提升一个元素都直接加分。

---

## ratio（用于 1_4，满分 score=2.0）

实现 `score_ratio` — `source/eval/score.py:74-85`：

```python
ref_list = [item.strip() for item in reference.split(",")]   # 仅按英文逗号切，逐段 strip
ans_list = [item.strip() for item in answer.split(",")]
hits = 0
for index, ref_item in enumerate(ref_list):
    if index < len(ans_list) and ans_list[index] == ref_item:  # 同位置全等
        hits += 1
earned = score * hits / len(ref_list)
```

精确语义（对 skill 输出的硬约束）：

- **分隔符固定为英文逗号 `,`**。元素内部不得含逗号。
- **按位置（positional）比较**：`ans[i]` 必须等于 `ref[i]`。顺序错位即扣分。→ 失败用例 ID 必须**按 test_cases.json 出现顺序**排列。
- 每段两侧 `strip()`，但**区分大小写、区分内容**（`ans_list[i] == ref_item`，精确字符串相等）。
- 分母是 `len(ref_list)`。若答案比参考短，缺的位置算错；若答案更长，多出的尾段不影响（只遍历 ref 的下标），但会把后续元素挤位（因为位置敏感）——所以**多输出一个错误 ID 会让它之后所有位置错位**，比漏报伤害更大。
- 1_4 参考答案：`TC009,TC011,TC014,TC015,TC016,TC020`（6 个失败用例，分母=6，每命中一个 +2.0/6≈0.333）。来源 `question_disc.json` 1_4 项 `reference_answer`。

ratio 风险点：因为位置敏感且不排序，skill **必须保证“按 test_cases 顺序收集失败 ID、不补漏不多报”**。多报/少报/乱序都会连累后续位置。

---

## list_equal（用于 3_3，满分 score=5.0）

实现 `score_list_equal` — `source/eval/score.py:56-71`，解析辅助 `_parse_list_like` — `source/eval/score.py:39-48`：

```python
def _parse_list_like(text):
    stripped = text.strip()
    try:
        value = json.loads(stripped)         # 先按 JSON 数组解析
        if isinstance(value, list):
            return [str(item) for item in value]
    except (ValueError, TypeError):
        pass
    return stripped.split(",")               # 退化：按逗号切

def score_list_equal(reference, answer, score):
    ref_list = [item.strip() for item in _parse_list_like(reference)]
    ans_list = [item.strip() for item in _parse_list_like(answer)]
    used = [False]*len(ans_list)
    hits = 0
    for ref_item in ref_list:                # 逐元素无序匹配（贪心，每个 ans 元素只用一次）
        for index, ans_item in enumerate(ans_list):
            if not used[index] and ans_item == ref_item:
                used[index] = True
                hits += 1
                break
    earned = score * hits / len(ref_list)
```

精确语义（对 skill 输出的硬约束）：

- **答案是一个 JSON 数组文本**（顶层 `json.loads` 必须得到 list）。3_3 题面也要求 “answer 仅返回 JSON 数组文本”。
- 数组**元素粒度**：每个元素是一整个字符串 `"题目ID=>persona_phrase|||reply|||service_action"`。匹配时**整段字符串必须与参考的某个元素逐字符全等**（`ans_item == ref_item`，仅两端 strip）。
- **匹配是无序集合式**（逐 ref 元素去 ans 里找一个未用过的相等项）。所以**元素顺序不影响 list_equal 得分**——但 3_3 题面仍要求按 dialog 顺序排列，建议照做以防平台另有校验，且代价为零。
- 分母 `len(ref_list)` = 30（3_3 参考答案含 30 个元素）。每命中一个完整元素 +5.0/30≈0.167。
- **“逐元素全等”对每一段都致命严格**：`题目ID`、`persona_phrase`、`reply`、`service_action` 四部分加上分隔符 `=>` / `|||` 必须与参考完全一致。任一字符不同（多空格、改写、翻译、删减、补字）→ 该元素 0 分。
- 因为是整段比较，**reply 必须取来源原文（Wiki FAQ `a` 或 DB `messages.content`），service_action 必须取 `service_action_options` 原文，persona_phrase 必须严格按 persona 称呼规则生成**。三者任一错位，整段丢分。

list_equal 风险点：这是两题里最难拿满分的——30 个元素，每个元素任意一处字符漂移就丢 1/30。最大难点是 reply 的**原文逐字匹配**（不能让模型改写/总结/翻译）。

---

## 与 skill 输出对接的结论

| 题 | type | 输出形态 | 致命约束 |
|---|---|---|---|
| 1_4 | ratio | `"TCxxx,TCyyy,..."` 逗号分隔字符串 | 按 test_cases 顺序、位置敏感、精确相等、不多报不漏报 |
| 3_3 | list_equal | `'["ID=>p\|\|\|reply\|\|\|action", ...]'` JSON 数组文本 | 每元素四部分逐字全等；reply/action 取原文不得改写；persona 按规则；建议按 dialog 顺序 |

两题 skill 的最终 `answer` 字段（main agent 取 `answer` 原样提交）必须就是上面这两种字符串，**不得带解释、不得加包裹**。
