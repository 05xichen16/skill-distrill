# Journal - xichen (Part 1)

> AI development session journal
> Started: 2026-06-10

---



## Session 1: 阶段B：评测工具固化 + 2_2 确定性 skill

**Date**: 2026-06-11
**Task**: 阶段B：评测工具固化 + 2_2 确定性 skill
**Branch**: `develop`

### Summary

固化判分逻辑为评测工具/回归台(source/eval；baseline 重现 12.386/32，白送分锚点 1_1=2/1_3=2/3_2=5 全中)；新增 2_2 敏感信息扫描确定性 skill(递归解 zip+tar+边界正则，文本计数 2782/3479/2299/3562；图 OCR 逐字转写+优雅降级)；补 mcp_client skill_run 的 question_dir 注入。回归台确认 1_1/1_3/3_2 未破坏。还原了 trellis-check 越界改的图片上限默认值。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `de03770` | (see git log) |
| `a01523b` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: 阶段B-3_1: 提示词学习与推理通用分类 skill (+4.05/5)

**Date**: 2026-06-11
**Task**: 阶段B-3_1: 提示词学习与推理通用分类 skill (+4.05/5)
**Branch**: `develop`

### Summary

新增通用 prompt-learning 图像分类 skill prompt_learn_classify(类别从训练标签动态发现/判别规则由 agent 传题面 task_description/验证集动态枚举/逐图多模态+重试兜底不缺段/有界并发/self-eval；非手套专用，扛隐藏变种)。修 contestant_agent._iter_image_files: 声明目录的图片默认不自动注入(env 可逆)，交给 skill 逐图——修掉注入6张误导图致模型不调skill只出6段的集成坑(2_1同样受益)。+17单测(全套27绿)。DashScope实测:训练集20张 zero-shot+thinking=false=85%(thinking=true反而75%/过判)；完整agent链路满跑验证集100张→模型自主skill_run→3_1=4.05/5(81/100)，投影总分→~19/32。回归台exit0白送分1_1/1_3/3_2全守。本轮归档 06-11-b-3_1 与遗留已完成的 06-10-a。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `83c7ad4` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
