# PRD — 阶段B 1_2「华为编程规范问答」N段格式化 skill（止方差）

## Goal
把 1_2 从「无 skill、模型自由判题 → 方差 0.2↔1.4」转成**确定结构 + 文档接地**的 QA skill，稳定拿 1.5–2.0/2。
本质：1_2 不是确定性计数（像 2_2/3_1），答案需**读规范文档理解**=模型判题；但**失分主因是格式/语言纪律**（不是不会答），用 skill 强制格式 + 文档接地即可大幅去方差。

## What I already know（已取证，勿重推）
- **判分**：`match1`、`score=2`、按 **`;`** 切段、每段按算子**子串**判定（or/and/contain），得分=命中段/len(ref)×2。公开 rubric：
  `or[安卓,android,Android];and[L];and[标准库,第三方库,应用程序自定义模块];or[is,is not];and[cpp,h];and[同时];and[大驼峰];and[===,!==];and[password];and[HttpOnly]`
- **题面自带硬指令**（这次违反它才丢分）：① 即使英文提问，答案必须用规范文档**原文**（非英文翻译）；② **用英文分号 `;` 分隔、按 Q1~QN 顺序**。
- **这次跌分根因（已诊断）**：模型用**英文**作答（命不中中文算子 安卓/标准库/同时/大驼峰）+ **把 1 段拆成多段**（变 12 段→位置全错）→ 7/10→1/10。答案是正常规范内容、**没误用其它 skill**，纯无结构兜底时的语言/分段漂移。
- **隐藏变种**（explanation）：① 每规范问题数不固定；② 问题顺序可调整；③ **规范文档内容不变**（固定知识库）。→ **必须通用**：动态解析题面 N 个问题、不写死 10/答案；文档当固定 KB 检索。
- **素材**：`编程规范/` 下 5 个规范各有 `.docx`+`.md` 两版；**`.md` 是可读文本**（docx 是二进制）。5 个 .md 合计 **~1.57MB → 不能整本喂每次调用**（爆上下文）。答案可检索：Python.md `G.FMT.07` 一行含「标准库、第三方库、应用程序自定义模块」；Web安全.md 有 `type="password"`/`HttpOnly`；Java.md 有 安卓/android/com.huawei 段。
- **题面分组**：问题按 `【Java规范】/【Python规范】/【C++规范】/【JS/TS规范】/【Web安全规范】` 分组 → 每问可路由到对应规范 .md。
- **集成栈**（同 2_2/3_1）：skill 三件套(SKILL.md+skill.json+scripts/run.py)、stdin JSON/stdout、`_runtime.question_dir` 注入、多模态/文本模型调用复用 sensitive_scan/prompt_learn_classify 的 HTTP 结构、从 `os.environ` 读 MODEL_*。**本题纯文本**（无需图片）。`编程规范/` 是声明目录、本任务无关图片路由。

## Requirements（evolving）
- 新 skill（暂名 `spec_qa` / `standards_qa`）：
  - **解析题面**：从 `task_description` 动态抽取 N 个子问题（`Q\d+:` 或 `【X规范】` 分组），保序。不写死题数/答案。
  - **路由**：每问按其 `【X规范】`组头映射到对应规范 `.md`（按 Java/Python/C++/JS&TS/Web安全 关键词匹配文件名）。
  - **检索**：在该 .md 内按问题关键词检索相关片段（控制片段体量，token 友好）。
  - **作答**：逐问让模型基于片段答，**强约束**：用文档**原文措辞/原语言**（中文规范→中文答）、简洁、只给答案。
  - **格式**：**代码**把各答案用 `;` 按 Q 序拼成恰好 N 段（杜绝模型乱分段）。
  - 输出 stdout JSON：`{answer, per_question:[{q,answer,source}], n, warnings}`；`answer` 即最终。
  - 兜底：单问检索/调用失败→该段给保守占位（保持段数/位置）+warning，绝不崩、绝不少段。
- `SKILL.md` 指示模型：遇「编程规范/标准问答（读规范文档答 N 问、`;` 分隔）」题，调 skill、传 `task_description`+规范目录、**原样返回 `answer`**。
- 离线单测：题面解析(N 可变/乱序)、规范路由、`;` 代码拼接 N 段、原语言约束、兜底。

## Decision (ADR-lite)
- **[已定] 调用粒度 = 逐问 N 次调用（Approach A）**。每问独立检索对应规范 .md 片段 + 单独调模型答 1 句；**代码**把 N 个答案用 `;` 按序拼成恰好 N 段。理由：用户目标是「止方差」，A 让段数由代码保证、每问聚焦、逐问强制原文/原语言，去方差最彻底；正确性>>token，N≈10 次小调用成本可接受。
- **[已定] `.docx` 兜底 = 加轻量降级**。优先读 `.md`；若某规范只有 `.docx`（变种保险），解 zip 取 `word/document.xml` 去 XML 标签提文本。低成本插一段，不依赖 .md 一定在。
- **[已定] 无组头/路由失败兜底**：题面 `【X规范】`组头→按关键词(Java/Python/C++/JavaScript|TS/Web|安全)映射 .md；若某问无法判组或映射不到，**退化为在全部规范里检索**该问关键词，绝不漏答。

## Acceptance Criteria（evolving）
- [ ] 离线单测全绿（解析/路由/拼接/兜底）；不破坏现有 27 测。
- [ ] DashScope 实测 1_2：输出恰好 N 段 `;` 分隔、答案为规范原文/原语言；`eval/score` 给 1_2 **稳定 ≥1.5（目标 ≥1.8）**，且**多次跑波动小**（去方差是核心验收）。
- [ ] 回归台 exit0，白送分 1_1/1_3/3_2 不回归。
- [ ] 通用性：题数/顺序/答案全动态，无硬编码；文档当固定 KB。

## Out of Scope
- 不动判分/回归台/其它题 skill / 图片注入路由 / `AGENT_DEMO_MAX_IMAGES`。
- 不硬编码 10 个公开答案；不为 1_2 牺牲白送分。

## Technical Notes
- 范本：`source/solution/skills/prompt_learn_classify/scripts/run.py`（目录解析/`_runtime`/模型 HTTP 调用/逐项重试兜底/纯 ASCII 源码）。
- 判分语义：`source/eval/score.py::score_match`（match1 用 `;`、子串算子）。
- 验证：单题 json `publish/publish_V1/q_1_2.json`（gitignored）走 `python -m source.main`；`python -m source.eval.score`。
- Windows GBK：测试 `PYTHONIOENCODING=utf-8`、源码纯 ASCII、中文只在数据/prompt 串里。
