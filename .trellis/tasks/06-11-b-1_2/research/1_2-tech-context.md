# 1_2 实现技术上下文（已取证/已 grep 验证）

复用与锚点，供 implement 直接照搬，少走弯路。判分/通用性/方案见 `../prd.md`。

## 复用脚手架（照 prompt_learn_classify 抄）
`source/solution/skills/prompt_learn_classify/scripts/run.py` 已有可直接复用的部件：
- `_model_config()`：从 `os.environ` 读 `MODEL_CHAT_COMPLETIONS_URL`/`MODEL_BASE_URL`/`MODEL_API_KEY`/`MODEL_NAME`/`PACKAGE_ID`。
- 模型 HTTP 调用（urllib + `http.client` fallback、双 `package_id`/`packageId` header、`chat_template_kwargs.enable_thinking`、`_extract_content`）。**本题纯文本**：`messages[0].content` 只放 `[{"type":"text","text": prompt}]`，不要图片块。
- `resolve_dir()` / `_candidate_dirs()`：相对目录→`_runtime.question_dir`→cwd 解析，可改造成解析 `编程规范/`。
- `_read_stdin_text()` / `_emit()`：Windows GBK 管道下 stdin/stdout 编码鲁棒（含中文目录/题面必须用，否则崩）——**直接照搬**。
- 逐项重试+兜底骨架（`_predict_one` 的 retry/backoff/fallback、ThreadPoolExecutor 有界并发、按序号重排）。本题逐问可并发，但**答案拼接必须按 Q 序**。
- 纯标准库、Python 3.9、纯 ASCII 源码（中文只在数据/prompt 串）。

## 判分锚点（match1）
`source/eval/score.py::score_match` + `_segment_matches`：按 **`;`** split；段算子 `or[a,b]`(含任一子串)/`and[a,b]`(含全部子串)/`contain[x]`/`is[x]`/字面量。
→ **答案段只需"包含"正确关键词即可命中**（子串，非全等）。策略：答案尽量含规范原文关键术语、原语言（中文规范→中文）。`match1` 用 `;`（其余 matchN 用 `,`）——本题就是 `;`。

## 知识源与已验证答案锚点
`publish/publish_V1/编程规范/`：5 规范各有 `.docx`(二进制) + `.md`(可读文本)，**用 .md**。5 个 .md 合计 ~1.57MB → 禁整本喂；按问检索片段。
- 题面组头→文件名关键词映射：`Java`→`华为Java语言编程规范V5.x.md`；`Python`→`华为Python语言编程规范V3.x.md`；`C++`→`华为C++语言编程规范V5.x.md`；`JS/TS`→`华为JavaScript&TypeScript语言编程规范V3.x.md`；`Web安全`→`华为Web应用安全开发规范.md`。
- 已 grep 验证答案就在 .md 里（公开题示例）：
  - Python.md:1041 `G.FMT.07 导入部分(imports)应该按照标准库、第三方库、应用程序自定义模块的顺序排列导入`（Q3 三词全含）。
  - Web安全.md：`<input type="password" .../>`、`HttpOnly`（Q9/Q10）。
  - Java.md：`安卓`/`android`/`com.huawei`/包导入排序段（Q1）；long 字面量 `L` 后缀段（Q2）。
- 变种保险：某规范只有 `.docx` 时，解 zip 取 `word/document.xml`、去 `<...>` 标签提文本（轻量降级）。

## 检索建议
逐问：从问题文本抽关键词（去停用词/取实体词，中英都要），在映射到的 .md 内找命中行、取上下 ~10–20 行窗口作片段喂模型；判不了组或映射不到→在全部 .md 检索兜底，绝不漏答。
