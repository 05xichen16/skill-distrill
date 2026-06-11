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


## Session 3: 阶段B-1_2: 编程规范问答 spec_qa skill (止方差,稳定满分2.0/2)

**Date**: 2026-06-11
**Task**: 阶段B-1_2: 编程规范问答 spec_qa skill (止方差,稳定满分2.0/2)
**Branch**: `develop`

### Summary

新增通用文档接地 QA skill spec_qa(动态解析题面 N 子问题→按【X规范】路由到规范.md→关键词检索片段→逐问单独调模型答→代码用;拼恰好N段)。把 1_2 从 baseline 1.4(且 0.2↔1.4 乱跳)做成稳定满分 2.0/2。关键调参:检索片段必须大(SPEC_QA_SNIPPET_CHARS=25000,小片段让中文文档里英文提问命不中→模型答未提及只0.8);build_prompt 优先文档否则用知识(救文档覆盖稀疏题如 None 比较用 is/is not)。+26 单测(全套53绿)。DashScope 实测:直接跑3次全2.0/spread=0;完整 agent 链路模型自主 skill_run 也 2.0。回归台 exit0 白送分1_1/1_3/3_2不回归。投影总分 19.436→21.236/32。本任务按用户要求跳过 trellis-check,改用离线单测+3次跑验零方差+完整链路+回归把关。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ba7c22a` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: 关thinking默认+题级并发=3:修1小时只跑完4/10题

**Date**: 2026-06-11
**Task**: 关thinking默认+题级并发=3:修1小时只跑完4/10题
**Branch**: `develop`

### Summary

正式环境实测撞任务书§281的1小时运行上限,10题只跑完4题(6题空答)。根因:.env AGENT_DEMO_ENABLE_THINKING=1使每次模型调用~10×慢且被skill子进程继承(prompt_learn_classify逐张分类≈100次调用)+CONCURRENCY=1串行。修复:全局关thinking(默认False+按题白名单AGENT_DEMO_THINKING_QUESTION_IDS路由)、env_config默认对齐、题级并发=3(skill worker维持4,峰值~12)。验证:53单测passed+回归台exit0(白送分守住)+并发分支确认。真机提速待生产验证;网关限流则CONCURRENCY调2。墙钟软截止兜底留作fast-follow。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `16aa96a` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: 补 interface_test(1_4)+wiki_dialog(3_3) skill,端到端实测+6.33/7

**Date**: 2026-06-11
**Task**: 补 interface_test(1_4)+wiki_dialog(3_3) skill,端到端实测+6.33/7
**Branch**: `develop`

### Summary

1_4/3_3 此前无skill白丢7分。新增两个通用纯标准库自动发现零硬编码skill:interface_test(1_4,LLM解析description→结构化HTTP步骤+代码断言+串行+每写步骤取新token+整轮固定X-Package-Id+失败ID代码join)、wiki_dialog(3_3,预加载权威候选池[DB带message_actions标注消息+wiki带service_action_key的FAQ]+LLM只选候选索引不生成文本+reply/action代码取原文+persona代码拼+key_map+DB标注源优先)。DashScope 35B-A3B端到端实测:1_4=2.0/2(6/6)、3_3=4.333/5(26/30),投影19.35→~25.7/32。102离线单测全绿+回归台exit0。模型本session换成Qwen3.5-35B-A3B(已记忆)。研究落盘research/(服务契约+30答案反向追溯)。3_3余4/30=选错候选可再调。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8d254f1` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: 修复 2_3/3_2 skill 超时归零: 预算修正+deadline 自保+router 出口门禁

**Date**: 2026-06-11
**Task**: 修复 2_3/3_2 skill 超时归零: 预算修正+deadline 自保+router 出口门禁
**Branch**: `develop`

### Summary

本地全量验证定位两处 skill route failed 根因: po_compliance_audit 60s 超时是纯代码版遗留(混合 LLM 版 14 PO 深审必死), java_tax_calculator 240s 兜不住 3 轮修复循环最坏情况; 外层 subprocess kill 导致脚本内兜底无机会输出, 3_2 落 model loop 后提交 4096 截断裸 CoT(model loop 出口零门禁)。任务书核实平台仅 1h 总限无每题时限。修复: 超时 600/480 + skill_runtime 注入 SKILL_BUDGET_SECONDS + 两脚本 deadline 自保 + model loop 出口复用 _skill_answer_guard(拒则严格重试一次) + 新增 po shape guard + finish_reason=length 不作终答 + skill 内 _call_model 5xx 重试 + 每题耗时日志。实测 po skill 真实端点 150.4s/8-9 gold, pytest 188 passed(+16, 0 回归)。用户要求跳过 trellis-check。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `5dfc45f` | (see git log) |
| `b5be787` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
