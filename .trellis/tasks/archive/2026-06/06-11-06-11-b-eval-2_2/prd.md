# PRD — 阶段 B：评测工具固化 + 2_2 确定性 skill

## 背景与定位
华为 Agent 个人赛 Phase B。Phase A（框架硬化）已完成。本任务两件事：
1. **把判分逻辑固化成评测工具（回归台）**——每次改动后能一键给 `results.json` 打分，守住白送分、量化新增分。
2. **做 2_2「敏感信息扫描」确定性 skill**（解压 + 正则 + 图 OCR），把 baseline 的 2_2=0 拉到满分（+3）。

排名次序：**正确性 >> token >> 提交次数**。绝不为省 token 牺牲正确性。

## 关键事实（已实测，勿重新推导）

### 判分语义（已用 baseline 校准，总分重现 12.386/32 ≈ 记忆里的 12.4）
公开答案/分值/判分类型在 `publish/publish_V1/question_disc.json`，字段 `type/score/reference_answer`。各 `type` 语义（重建并校准过）：
- `equal`：strip 后**全等**才给满分，否则 0。（3_2）
- `list_equal`：把 ref/ans 当 **JSON 数组**解析（解析失败再退化为逗号split），逐元素 strip 后比对，得分 = score × 命中数/len(ref)。（3_3，元素内含逗号，必须 JSON 解析）
- `ratio`：按 `,` 切分，**按位置**比对，得分 = score × 命中位置数/len(ref)。（1_1/1_4/2_1/2_2）
- `matchN`：按分隔符切分（**match1 用 `;`，其余用 `,`**），每段按其算子判定，得分 = score × 命中段数/len(ref)。段算子：
  - `or[a,b,...]`：段文本**包含任意一个** a/b/...（子串）
  - `and[a,b,...]`：段文本**包含全部**
  - `contain[x]`：包含 x
  - `is[x]`：段文本 strip 后**等于** x
  - 无方括号：字面量，**strip 后全等**
  - 特例 `match5`（1_3）：按 `,` 切 3 段，前两段字面全等，**第三段按顿号「、」切成集合做集合相等**（根因关键词无序）
- 锚点（必须复现）：**1_1=2.0、1_3=2.0、3_2=5.0**；baseline 总分 **12.386/32**。

> 注：平台真实判分的「部分分」公式是隐藏的；本工具的 match/ratio 部分分是按上述重建实现，已用三个白送分锚点 + 总分 12.386 校准对齐。白送分判定（equal/全等、ratio 全对）与平台一致，回归台对「守白送分 + 量化 2_2」是可靠的。

### 2_2 正则拆解（已实测，文本+图片 = 标准答案）
zip `publish/publish_V1/sensitive_data_2_1.zip` 结构：12 个文本文件(.txt/.log)、6 张图片(png/jpg)、4 个 .tar（tar 内含子目录与文件，需递归解）。
标准答案 `2806,3495,2328,3591`（手机,邮箱,身份证,APIKey），**统计总出现次数，不去重**。
- **文本部分（确定性，正则）**：手机=2782、邮箱=3479、身份证=2299、APIKey=3562
- **图片部分（需视觉 OCR）**：手机+24、邮箱+16、身份证+29、APIKey+29
- 两者相加 = 标准答案，**逐项吻合**。
正则（边界很关键）：
- 手机 `(?<!\d)1\d{10}(?!\d)` —— **必须加边界**；无边界版 `1\d{10}` 会命中 18 位身份证内部子串，得 4922（爆表）
- 邮箱 `[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.com`（公开集只有 .com → 3479）
- 身份证 `(?<!\d)\d{17}[\dXx](?!\d)` → 2299
- APIKey `sk-\S+` → 3562（`sk-[A-Za-z0-9]+` 同为 3562）

### 集成/管线现状（已读源码）
- skill 契约：`source/solution/skills/<name>/` 下 `SKILL.md`(frontmatter name/description)+`skill.json`(entrypoint/input_schema/timeout_seconds)+`scripts/run.py`。`SkillRuntime.run_skill` 用 `subprocess.run([python, script], input=stdin_json, cwd=skill_dir, timeout=timeout_seconds)`，**stdin 收 JSON、stdout 出结果**。
- **路径缺口**：`text_read_file` 在 `LocalMCPClient.call_tool` 里用 `question_dir` 解析相对路径并校验；但 **`skill_run` 没有**——`runtime_context`(含 `question_dir`)没进 skill。所以 skill 现在定位不了题面相对路径的 zip。→ 需补注入。
- **package_id / 模型配置免管线**：`start.sh` `export PACKAGE_ID`/`packageId`；`ModelConfig.from_env()` 从 `os.environ` 读 `PACKAGE_ID`/`MODEL_*`；skill 子进程继承父环境（父进程已 `load_dotenv`）。→ skill 可直接 `os.environ` 自取模型配置 + package_id 做图 OCR、透传 `package_id`+`packageId` 双 header。
- 本机限制：内网网关 POST 一律 RemoteDisconnected（环境问题）；无 Java；DashScope 可作 Qwen3.5 多模态替身（`qwen3.5-122b-a10b`）。Windows 控制台 GBK：测试脚本带 `PYTHONIOENCODING=utf-8`、勿打印非 ASCII 符号。

## 范围内（必须做）
1. **评测工具**（`source/eval/score.py` + `__init__.py`）：
   - `score_results(results_list, disc_list) -> {per_question:[{id,type,score,earned,detail}], total, max}`，实现上述全部 type 语义。
   - CLI：`python -m source.eval.score <results.json> <question_disc.json>`，打印每题 type/score/earned + 总分（纯 ASCII）。
   - 验收：对 `source/outputs/baseline.json` + `question_disc.json` → 总分 **12.386±0.02**、**1_1=2.0 / 1_3=2.0 / 3_2=5.0**。
2. **回归台**（`source/eval/regression.py` 或并入 score 的 `--check`）：对一个 results.json 打分并**对比白送分阈值**，若 1_1<2 或 1_3<2 或 3_2<5 则非 0 退出并高亮；打印 2_2 当前得分。
3. **2_2 skill**（`source/solution/skills/sensitive_scan/`）：
   - `run.py`：读 stdin `{zip_path, _runtime:{question_dir,...}, do_ocr(默认true)}`；解析 zip 路径（abs 直接用；相对则 question_dir/zip_path，再 fallback cwd）；递归解 zip + 嵌套 tar；
     - 文本：上述 4 条边界正则计数（**总出现次数**）；
     - 图片（do_ocr）：base64 + 读 `os.environ` 的 MODEL_*/PACKAGE_ID，POST 网关（`package_id`+`packageId` 双 header、`enable_thinking=false` 省 token），prompt 让模型**逐字转写图中所有文本**，再对转写文本套**同样 4 条正则**计数累加（OCR 只做转写，计数仍确定性）；
     - **优雅降级**：模型未配置/调用失败 → 跳过 OCR、记 warning、保留文本计数，**绝不崩**；
     - stdout JSON：`{answer:"手,邮,证,key", breakdown:{text,image,total}, images_total, images_ocr_ok, warnings}`。
   - `skill.json`：entrypoint=scripts/run.py、`timeout_seconds`=300（OCR 联网）、input_schema 描述 zip_path/do_ocr。
   - `SKILL.md`：指示模型——遇「压缩包敏感信息扫描」题，调 `skill_run(name=sensitive_scan, arguments={zip_path:<题面声明的 zip>})`，**原样返回 `answer` 字段**，不要自己重数。
4. **补 skill_run 路径注入**（`source/runtime/mcp_client.py` `call_tool`）：当 `name=="skill_run"` 时，把 `question_dir`/`allowed_file_paths`/`question_id` 注入到 `args["arguments"]["_runtime"]`。镜像 `text_read_file` 的解析模式，低风险。
5. **离线单测**（`source/eval/` 或 `tests/`）：
   - 判分锚点测试：baseline → 12.386 + 三锚点。
   - skill 确定性测试：对真实 zip `do_ocr=false` → 文本计数 == (2782,3479,2299,3562)、images_total==6。**纯离线、不联网**。

## 范围外
- 其它题型 skill、few-shot、复核/自一致性、token 定版。
- 2_2 图 OCR 的真机端到端（需放通网关或切 DashScope）——本任务只做到离线确定性可验证 + OCR 代码就位 + 优雅降级；联网端到端作为后续手动验证。

## 验收
- `python -m source.eval.score source/outputs/baseline.json publish/publish_V1/question_disc.json` → 12.386±0.02，三锚点满分。
- skill 离线测试通过：文本 (2782,3479,2299,3562) + 6 图。
- **不碰 1_1/1_3/3_2 的代码路径**（它们不走 skill_run；唯一共享改动是 skill_run 注入，对它们无影响）——需在报告中明确说明并用回归台复测确认未回归。
- 纯标准库，Python 3.9.9 兼容（不用 3.10+ 的 match 语句等）。

## 风险
- 邮箱/身份证/sk 在变种里若出现非 .com 邮箱、19+ 位数字、含内部连字符的 key，正则需相应放宽——当前以公开集精确复现为准，变种留待真机微调。
- 图 OCR 计数依赖模型转写质量；用「转写+确定性正则」而非「让模型直接数」以最大化稳定。
