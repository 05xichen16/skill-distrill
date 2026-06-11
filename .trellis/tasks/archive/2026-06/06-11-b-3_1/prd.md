# PRD — 阶段 B：3_1「提示词学习与推理」通用图像分类 skill

## 背景与定位
华为 Agent 个人赛 Phase B。承接 2_2（已闭环 +3 坐实，回归台/评测工具已就绪）。
本任务做 **3_1**：题面「提示词学习与推理」——给一个**有标签的训练集**学规则、对**无标签的验证集**逐张分类。

- **分值/判分**：`score=5`，`type=match4`，**最大单题头**，本地可联网验证。
- **排名次序（决定战术）**：正确性 >> token >> 提交次数。token 仅在积分打平时生效，绝不为省 token 牺牲正确。
- **本题公开任务**：图中**长筒手套**三分类（PASS/FAIL/NOT_INVOLVED）。但见下「通用性硬约束」——**禁止写死手套/三类/100**。

## 关键事实（已读源码/已实测，勿重新推导）

### 判分语义 `match4`（已在 `source/eval/score.py` 实现并用 baseline 校准）
- 按 `,` 切分；每段是**字面量算子** → 命中条件 `segments[i].strip() == reference[i].strip()`（见 `score.py:_segment_matches` 末支 + `score_match`）。
- `reference_answer` = `1NOT_INVOLVED,2PASS,3PASS,...,100PASS`（每段 `<序号><标签>`，无空格）。
- 得分 = `score × 命中段数 / len(ref)` = **命中数 / 100 × 5**，**部分分**（不需全对）。
- ⚠️ **位置 + 字面双重约束**：预测段必须既在正确位置、又精确等于 `<i><LABEL>`。故输出必须**按数字序枚举验证集**、每段 `<i>` 前缀正确、`<LABEL>` 精确大写、无多余空格/标点。
- 公开答案在 `publish/publish_V1/question_disc.json`（仅供 eval 打分用）。正式赛是隐藏变种 → **skill 绝不读 disc、禁硬编码答案**。

### 题面三分类规则（本题公开版；通用解法须从 `task_description` 动态取，不写死）
> 地上或人手上出现长筒手套 → PASS；未看到人手的部分 → NOT_INVOLVED；看到的所有人手都没有长筒手套 → FAIL。
> 决策优先级（隐含）：手套出现(地上/手上)优先判 PASS；否则看人手是否可见：不可见→NOT_INVOLVED，可见但都无手套→FAIL。

### 通用性硬约束（来自题面 `explanation`，最关键）
`explanation`：「1、任务类型可能变化；2、训练集规模可能变化；3、验证集规模可能变化；4、输出类别数量可能变化」。
→ skill **必须做成通用 prompt-learning 图像分类器**：
- **类别集**从训练集标签**动态发现**（去重），不写死 PASS/FAIL/NOT_INVOLVED、不写死 3 类。
- **分类规则**由 agent 把题面任务描述作为参数传入（题面在模型上下文里），不写死手套逻辑。
- **验证集规模**动态枚举（有几张图就输出几段），不写死 100。
- 训练集规模动态（有几对 图+标签 就用几对）。

### 本地素材（已确认，2026-06-11）
- 训练集 `publish/publish_V1/训练集/`：20 张 `<n>.jpg`(n=1..20) + 同名 `<n>.txt` 标签（**无尾换行**）。
  分布：FAIL×6(1,2,6,18,19,20)、PASS×7(3,4,5,7,9,11,17)、NOT_INVOLVED×7(8,10,12,13,14,15,16)。**有真标签 → 可本地量准确率**。
- 验证集 `publish/publish_V1/验证集/`：100 张 `<n>.jpg`(n=1..100)，**无标签**。
- 题面 `files = ["./训练集/", "./验证集/"]`（相对 question 文件目录）。

### 集成/管线现状（已读源码，与 2_2 同栈）
- **skill 契约**：`source/solution/skills/<name>/` 下 `SKILL.md`(frontmatter name/description) + `skill.json`(entrypoint/input_schema/timeout_seconds) + `scripts/run.py`。`SkillRuntime.run_skill` 用 `subprocess.run([python, script], input=stdin_json, text, capture_output, cwd=skill_dir, timeout=timeout_seconds)`。**stdin 收 JSON、stdout 出结果**；非零退出会被当失败抛。
- **`_runtime` 注入（已实现）**：`mcp_client._inject_skill_runtime` 在 `skill_run` 时注入 `arguments._runtime = {question_dir, allowed_file_paths, question_id}`。**不含题面规则** → 规则须由 agent 作参数传入。
- **路径解析**：`question_dir = question_path.parent`；`allowed_file_paths = [question_dir/f for f in files]` = [训练集 dir, 验证集 dir]。skill 子进程**直接按 question_dir + 相对目录名读盘**即可（`allowed_file_paths` 只约束 `text_read_file` 工具，不约束 skill 子进程读文件）。
- **多模态调用**：**直接复用 `sensitive_scan/scripts/run.py` 的 `ocr_image` 调用结构**（urllib + `http.client` fallback、`package_id`+`packageId` 双 header、base64 data URL、`chat_template_kwargs.enable_thinking`、从 `os.environ` 读 `MODEL_CHAT_COMPLETIONS_URL`/`MODEL_API_KEY`/`MODEL_NAME`/`PACKAGE_ID`）。**DashScope 已实测接受该 payload**（2_2 端到端 6/6 图 OCR 成功）。可把图像调用逻辑抽出复用，避免重复实现。
- **agent 呈现**：`available_skills`(name+description) 进系统提示 → 模型自主 `skill_load` → `skill_run` → **原样输出 `answer`**（2_2 已实测模型会自动选用 skill 并原样返回）。
- **`_image_blocks` 默认塞前 6 张图**：对 3_1 是 token 浪费但**不影响正确性**（skill 自己逐图调模型，不依赖 agent 注入）。**本任务不动该上限**（Phase A 安全阀，曾被误改为无限已还原；token 仅 tiebreaker）。「按目录型多图题路由跳过注入」是后续可选优化，**本任务范围外**。
- **本机限制**：内网网关 POST 一律 `RemoteDisconnected`（环境问题，非代码）；DashScope 作 Qwen3.5 多模态替身可用；Windows 控制台 GBK → 测试加 `PYTHONIOENCODING=utf-8`、勿打印非 ASCII 符号。

## 范围内（必须做）

### 1. 新 skill `source/solution/skills/prompt_learn_classify/`（通用，非手套专用）
命名与描述围绕题面家族「提示词学习与推理 / 训练集学规则→验证集逐条分类」，以便隐藏变种（任务类型可能变）也能语义命中；**不要叫 glove_*、描述不要写死手套**。

**`scripts/run.py`**（纯标准库，Python 3.9 兼容，参考 `sensitive_scan/run.py` 风格）：
- 读 stdin JSON：
  ```json
  {
    "task_description": "<题面任务描述原文（含三分类规则）>",
    "train_dir": "训练集",            // 可选，缺省从 _runtime/files 推断
    "val_dir": "验证集",              // 可选，缺省从 _runtime/files 推断
    "few_shot_k": 0,                  // 可选，默认 0（zero-shot）
    "_runtime": { "question_dir": "...", "allowed_file_paths": [...], "question_id": "3_1" }
  }
  ```
- **目录解析**：相对路径 → `question_dir/<dir>`，再 fallback cwd；缺省时从 `_runtime.allowed_file_paths` 里按名（含「训练」「train」/「验证」「val」启发，或顺序）挑，挑不到再用默认名。健壮：解析不到目录要给清晰错误。
- **读训练集**：枚举 `train_dir` 下图片，配同名 `.txt` 得 (图, 标签)。**类别集 = 训练标签去重**（保序）。训练集可空（无标签时退化为「仅用 task_description 中出现的类别」或纯规则约束）。
- **逐张验证集推理**（数字序枚举 `val_dir` 下所有图片）：每图调多模态模型，prompt =
  - `task_description`（题面规则原文）+
  - `few_shot_k>0` 时：附 K 张**均衡覆盖各类别**的训练样例（图 + 其标签）作 few-shot（默认 0，不附）+
  - 末尾硬约束：`Valid labels: <逗号连接发现的类别>. Respond with EXACTLY one label from this list, uppercase, nothing else.`
- **标签解析归一化**（关键，决定 match4 命中）：模型输出 → strip/upper；① 精确等于某类别则取之；② 否则在候选类别里按**长度降序**做 token/子串匹配（先匹配长的，避免 `NOT_INVOLVED` 被误判或被 `PASS` 抢先）；③ 都不中 → fallback 默认标签（训练里最频类别；无训练则类别集首个）并记 warning。
- **逐图重试 + 兜底**：每图最多 N 次指数退避重试（N 默认 2~3）；仍失败 → 赋 fallback 标签（**保证不缺段、位置不错位**）+ warning。**skill 绝不因单图失败而崩、绝不少段**。
- **有界并发**：线程池（worker 数 env 可调，默认 4）跑验证集，缩短墙钟；结果**严格按图序号重排**后拼接。
- **self-eval（白送的本地校准）**：预测每张图时，若该图旁存在同名 `.txt`（训练集场景），把其内容作 ground-truth 收集（**仅用于输出 `accuracy` 字段，绝不喂给模型/不参与预测**）；验证集无 `.txt` 则该字段为空。→ 令 `val_dir=训练集` 即可零成本量准确率。
- **输出**（stdout JSON）：
  ```json
  {
    "answer": "1PASS,2FAIL,...",
    "predictions": [{"idx":1,"label":"PASS"}, ...],
    "classes": ["PASS","FAIL","NOT_INVOLVED"],
    "val_total": 100, "ok": 100, "failed": 0, "fallback_used": 0,
    "accuracy": {"n":20,"correct":17,"acc":0.85} ,   // 有 .txt 时才有
    "warnings": []
  }
  ```
  `answer` 即最终答案（`<i><LABEL>` 逗号连接，数字序）。

**`skill.json`**：`entrypoint=scripts/run.py`、**`timeout_seconds=1800`**（100 张×联网调用，需大超时）、`input_schema` 描述 `task_description`(required) / `train_dir` / `val_dir` / `few_shot_k`。

**`SKILL.md`**：指示模型——遇「提示词学习与推理 / 给训练集学提示词再对验证集逐条分类」类题，调
`skill_run(name=prompt_learn_classify, arguments={task_description:<题面任务描述原文>, train_dir:<题面训练集目录名>, val_dir:<题面验证集目录名>})`，
**原样返回 `answer` 字段**作为最终答案，不要自己逐图判、不要重排/改格式。

### 2. 离线单测（不联网，CI 可跑）`source/eval/tests/test_prompt_learn_classify.py`
用 mock/可注入的模型函数（把图像调用抽成可替换的 callable，便于注入假响应），覆盖：
- 类别集从训练标签**动态发现**（含「类别数量可变」：给 2 类 / 4 类各测一次）；
- 标签解析归一化：精确、含噪（`"The answer is PASS."`）、`NOT_INVOLVED` 不被 `PASS`/子串误判、大小写；
- 单图失败 → fallback 且**段数不少、序号连续**；
- 按数字序拼接 `<i><LABEL>`（乱序输入也要正确排序）；
- self-eval accuracy 计算正确。

## 本地验证（联网，DashScope；分阶段控成本）
1. 造单题 json `publish/publish_V1/q_3_1.json`（**gitignored**；与 `question.json` 顶层 shape 一致、仅含 3_1 的公开字段——注意核对 `question_loader.load_questions` 期望的结构）。
2. **校准（训练集 20 张，有真标签）**：把 skill 的 `val_dir` 指向训练集跑一次，看 `accuracy`。zero-shot 准确率达标（目标 ≥0.75 起步）则定 prompt；偏低则调 prompt 措辞 / 试 `few_shot_k`>0 / 试 `enable_thinking`。**先调准再花钱跑验证集**。
3. **验证集 smoke（10~20 张）**：临时缩小 val 子集试跑，确认格式/链路。
4. **验证集满跑（定版前一次）**：
   `set -a; . ./.env.dashscope; set +a; PYTHONIOENCODING=utf-8 python -m source.main --question publish/publish_V1/q_3_1.json --output source/outputs/result_3_1.json`
   （走完整 agent 链路，确认模型自主 skill_load→skill_run→原样输出）。
5. **打分**：`python -m source.eval.score source/outputs/result_3_1.json publish/publish_V1/question_disc.json` → 看 3_1 earned（部分分，目标尽量高，远高于 baseline 0）。
6. **回归**：`python -m source.eval.regression source/outputs/<含白送分的 results> publish/publish_V1/question_disc.json` 守 1_1≥2 / 1_3≥2 / 3_2≥5（本任务只**新增** skill 文件，理论零回归，仍跑一遍确认）。
- ⚠️ **成本**：满跑 = 100 次多模态调用，token/时间不小。校准用训练集 20、smoke 用 10~20，满跑仅定版前一次。给网关/外发图片可能触发权限提示，按需批准。

## 范围外 / 不要做
- 不动 `_image_blocks` 上限（Phase A 安全阀）；不做「目录型多图题跳过注入」的路由优化（后续任务）。
- 不动 `source/eval/`（评测/回归台）与其它题的 skill。
- skill **不读** `question_disc.json` 的 reference；**不写死**手套/三类/100/具体答案。
- 不碰 3_2 / 1_1 / 1_3 白送分。

## 验收标准
- 离线单测全绿（类别发现 / 标签解析归一化 / 单图失败兜底 / 按序拼接 / self-eval）。
- 训练集 20 张本地自评准确率**可量化并报数**。
- 验证集满跑产出**格式正确的 100 段** `<i><LABEL>`，`eval/score` 给出 **3_1 earned > 0 且明显高于 baseline 0**（目标尽量高）。
- `regression` 通过（白送分不回归）。
- **通用性**：类别/目录/验证集规模全部从输入推导，源码无任何硬编码答案或手套专用分支。

## 流程
trellis-implement（实现 skill + 单测）→ 本地 DashScope 校准/验证 → trellis-check → 回归台 → Phase 3.4 主 agent 提交 → `/trellis:finish-work`。
归档遗留：Phase A 任务 `06-10-a` 实际已完成仍 in_progress，可在本任务收尾后 `task.py archive .trellis/tasks/06-10-a` 清理。
