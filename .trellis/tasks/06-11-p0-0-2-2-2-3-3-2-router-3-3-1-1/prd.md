# P0 修复平台 0 分题（2_2/2_3/3_2/3_3 + router 门禁 + 1_1）

## Goal

平台真实分 31.67/102，54 分丢在四道 0 分题（2_2=0/9、2_3=0/15、3_2=0/15、3_3=0/15），另 1_4=1.07/6、1_1=3/6 低于模型自由答水平。根因已核实（见 research/root-cause-analysis.md）：**平台真题题面与公开集逐字相同、变种只在附件数据**；崩掉的 skill 全是把公开集数据的实现细节当成不变量 + router 无质量门禁导致退化输出被原样提交。本任务按用户确认的优先级实施修复，目标平台分 → 60+。

## Requirements（实施顺序按风险低→高）

1. **P0-1 `sensitive_scan` OCR 并发化**（2_2，+6~9）：6 图串行 360s > 300s timeout 被 kill。改 ThreadPool 有界并发（仿 `prompt_learn_classify`），单图失败/超时降级计 0 并 warning，不整体死。顺手把写死的 4 类敏感类型按题面动态化（explanation 说类型可能增加）。
2. **P0-4 router 质量门禁 + `wiki_dialog` 退化自检**（3_3，+6.33 保底）：router 对 skill 返回的 answer 做通用门禁（空串/明显占位 → 回退模型循环）；wiki_dialog 输出前自检（reply 空率超阈值/候选池空 → 主动抛异常触发回退）。
3. **P0-5 `date_normalize` 逐行混合**（1_1，+1.9~2.5）：正则命中走正则、未命中**单行**走 LLM；整体失败仍回退模型。不再整题 raise。
4. **P0-2 `java_tax_calculator` 重写**（2_3，+10~15）：按题面流程真做——LLM 读源码修错 → javac 编译（报错喂回重修循环 ≤3 次）→ java 跑题面 5 个示例输入自校验 → 全过再跑 10 个隐藏用例 → 真实 `java -version` 拼第一段。fallback：LLM 从源码注释抽税率表 → python 计算。去掉对 `TAX_BRACKETS_ENCODED`/`DEDUCTION_POINT_ENCODED` Base64 字段名的依赖。
5. **P0-3 `po_compliance_audit` 混合化**（3_2，+8~15）：代码骨架（CSV 解析、VP 角色有效期比对、日期比较、升序输出）保留；金额阈值从题面 description 动态解析；状态词由 LLM 一次性分类（终态/非终态）；审批邮件逐封由 LLM 判语义（结构化输出 approved/covers_all_items/date/sender）；日期解析扩格式 + LLM 兜底；输出守卫（结果异常 → 回退）。
6. **P1（时间允许）**：1_4 `interface_test` 去 conservative-pass（解析/执行失败 → 重试或回退而非视为通过）；1_2 `spec_qa` 英文问题先 LLM 生成中文检索词；2_1 `purchase_clean_summary` 附件证据 LLM 化抽取。

## Acceptance Criteria

* [ ] 回归台 `python -m source.eval.regression` exit 0（白送分 1_1≥2/1_3≥2/3_2≥5 不回归）
* [ ] DashScope 35B-A3B 端到端全 10 题跑分 ≥ 当前基线 25.93/32，且修复题不低于修复前
* [ ] 2_2：6 图并发墙钟 <120s；单图模拟失败时输出仍含其余计数（降级不死）
* [ ] 2_3：本地 JDK21 全链路通（公开版源码 10 税额全对+版本段）；变种模拟（改税率表/错误位置/删 Base64 字段）下编译-自校验循环仍出正确答案或正确回退
* [ ] 3_2：公开集 9 PO 满分保持；扰动测试（日期 `2026.03.05`/`5 March 2026`、状态"已付款"/"settled"、阈值改 60000、邮件换措辞）判定正确
* [ ] 3_3：候选池空/DB 表名改名模拟 → skill 抛异常 → router 回退模型（不再占位提交）
* [ ] 1_1：公开集 30/30 保持；构造未匹配行走 LLM 行级兜底
* [ ] router 门禁：空 answer/占位 answer 回退模型，有单测
* [ ] 全部新增/修改逻辑有离线单测；`PYTHONIOENCODING=utf-8` 下全绿

## Definition of Done

* 单测+扰动自测+回归台+DashScope 端到端四层验证全过
* 不引入第三方依赖（判题机 Python 3.9.9 纯标准库）
* 1h 总预算友好：新增 LLM 调用计数有上限（3_2 邮件逐封、2_3 修码循环≤3、1_1 仅未命中行）
* journal 记录 + 提交

## Out of Scope

* 3_1 分类准确率微调、1_3 module fallback 改造（P3）
* 平台运行日志获取、token 压缩（正确性优先）
* 重交平台（用户手动操作）

## Decision (ADR-lite)

**Context**：四道 0 分题的确定性 skill 在隐藏变种上脆性崩溃；旧模型循环反而有部分分。
**Decision**：不回到纯模型循环，也不修补正则——采用「代码骨架 + LLM 语义判定 + 失败回退」混合架构；router 加通用质量门禁兜底。
**Consequences**：token 消耗上升（排序第二优先级，可接受）；2_3/3_2 引入模型不确定性，用题面自带 ground truth（2_3 示例 IO）和结构化局部判定（3_2 逐邮件）控制。

## Technical Notes

* 本地模型：`set -a; . ./.env.dashscope; set +a` 用 DashScope `qwen3.5-35b-a3b` 替身；生产 `fuyao-Qwen3.5`
* thinking 默认关（1h 预算杀手），别开回去
* 本机无 Java → 需装 JDK21（`winget install Microsoft.OpenJDK.21` 或 EclipseAdoptium.Temurin.21.JDK）
* Windows GBK 控制台：测试脚本必须 `PYTHONIOENCODING=utf-8`，避免打印非 ASCII 符号
* 单题子集 json 必须放 `publish/publish_V1/` 内（batch_runner 用 question_dir 解析相对 files）
* 根因行号级证据：research/root-cause-analysis.md
