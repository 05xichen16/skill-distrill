# Research: skill 结构模板要点（照搬现有三个 skill）

- **Query**: 两个新 skill 必须照搬的目录结构、_runtime 注入、模型调用、编码处理、降级策略
- **Scope**: internal
- **Date**: 2026-06-11

## 来源

- `source/solution/skills/spec_qa/`（最近、最完整，主参考）
- `source/solution/skills/sensitive_scan/`、`source/solution/skills/prompt_learn_classify/`、`source/solution/skills/mock_summary_skill/`（同范式）
- 每个 skill 目录结构（实测 `ls`）：`SKILL.md` + `skill.json` + `scripts/run.py`（+ `scripts/__pycache__`）。

## 1. 目录结构（必须照此）

```
source/solution/skills/<skill_name>/
  SKILL.md          # 触发说明 + how to call + what to return（人/agent 读）
  skill.json        # name/description/entrypoint/timeout_seconds/input_schema
  scripts/run.py    # 纯标准库 Python 3.9，stdin JSON -> stdout JSON
```

## 2. skill.json 模板

参考 `source/solution/skills/spec_qa/skill.json`：

```json
{
  "name": "<skill_name>",
  "description": "<一句话:做什么 + '通用,从输入派生,不硬编码' 的声明>",
  "entrypoint": "scripts/run.py",
  "timeout_seconds": 600,
  "input_schema": {
    "type": "object",
    "properties": {
      "task_description": {"type": "string", "description": "..."},
      "<dir_or_file_arg>":  {"type": "string", "description": "相对名解析自 question_dir;可选,缺省从 question 声明文件推断"}
    },
    "required": ["task_description"],
    "additionalProperties": true
  }
}
```

- `timeout_seconds`：sensitive_scan=300、spec_qa=600、prompt_learn_classify=1800。1_4（真调多接口）建议 ≥600；3_3（30 题各一次 LLM 选源）建议 ≥600，可更高。
- `additionalProperties: true`（runner 会注入 `_runtime` 等额外键）。

## 3. SKILL.md 模板

参考 `source/solution/skills/spec_qa/SKILL.md`：YAML frontmatter（`name` + `description`）+ 正文：何时用本 skill（触发信号）、how to call（JSON 示例）、what to return（**强调取 `answer` 字段原样提交，不要自行作答/重排/翻译/重切**）。

## 4. _runtime 注入（runner 提供，skill 必读）

stdin JSON 里 runner 注入 `_runtime`（见 `spec_qa/scripts/run.py:20-29, 746-748`）：

```json
{ "_runtime": {
    "question_dir": "<本题输入文件根目录的绝对/相对路径>",
    "allowed_file_paths": ["<题目声明的文件/目录列表>"],
    "question_id": "1_4"
} }
```

目录/文件解析模式（照搬 `spec_qa/scripts/run.py:113-157` 的 `_candidate_dirs` / `_pick_dir_from_allowed` / `resolve_*`）：
1. 显式参数（绝对路径直接用；相对名 join `question_dir`，再 cwd，再裸名）；
2. 退化到 `allowed_file_paths` 里第一个存在的目录/文件；
3. 再退化到默认名 join question_dir/cwd。
**永不因找不到文件就崩**，找最接近的候选并 warn。

## 5. 模型调用（照搬，最关键的复用点）

`_model_config()`（`spec_qa/scripts/run.py:504-528`）从**环境变量**读：
- `MODEL_CHAT_COMPLETIONS_URL`（或 `MODEL_BASE_URL`，自动补 `/chat/completions`）
- `MODEL_API_KEY`、`MODEL_NAME`
- `PACKAGE_ID` 或 `packageId`（二者其一）
- 三者（url/key/model）缺一 → 返回 `None` → skill 走**降级**（占位/跳过 LLM），不崩。

`answer_question(config, prompt, timeout)`（`spec_qa/scripts/run.py:531-603`）是**唯一可注入 seam**（离线测试 monkeypatch 它，import 时不触网）。要点：
- payload：`model` + `temperature:0.0` + `stream:false` + `chat_template_kwargs:{enable_thinking: <env AGENT_DEMO_ENABLE_THINKING 默认 false>}` + `messages:[{role:user, content:[{type:text,text:prompt}]}]`。
- 图片输入用 data URL（见 sensitive_scan / prompt_learn_classify 的 image_url base64；3_3/1_4 不需要图片，text-only 即可）。
- **双 header**：`Authorization: Bearer <key>` + 同时设 `package_id` 和 `packageId`（同一 PACKAGE_ID 值）→ `spec_qa/scripts/run.py:556-558`。
- urllib 优先，`http.client.RemoteDisconnected` 时 fallback 到 `_post_with_http_client`（`:570-590`）。
- `_extract_content`（`:593-603`）：取 `choices[0].message.content`，content 为 list 时拼接各 `text`。
- `chat_template_kwargs` 兼容坑见 MEMORY 的 DashScope 本地端点笔记（替身端点对该字段的处理）。本地调测端点见 `.env.dashscope`。

`PACKAGE_ID` 用法：**同一 package_id 在一次运行内保持一致**（服务/网关按 packageId 存运行态）。1_4 调 18081 的 `X-Package-Id` 与 LLM header 的 packageId 都用环境注入的同一值。3_3 调 18080 wiki 无需 package（wiki 服务不校验），但 LLM 调用仍带 packageId。

## 6. 编码 / IO 健壮性（Windows 必备，照搬）

- 读 stdin：`_read_stdin_text()`（`spec_qa/scripts/run.py:825-853`）——读 `sys.stdin.buffer` 原始字节，先 UTF-8 再 locale(cp936/GBK) 解码（runner 在 Windows 用 `subprocess.run(text=True)` 可能 GBK 编码管道，子进程可能 UTF-8，不处理会因中文崩）。
- 写 stdout：`_emit()`（`:856-873`）——`json.dumps(..., ensure_ascii=True)` 后写 **ASCII 字节**（中文走 `\uXXXX` 转义），避免 Windows 管道 codec 不匹配。
- 读文件：按 bytes 读再 UTF-8 解码（`_read_text_file` `:201-210`），`errors="replace"` 兜底。

## 7. 输出契约

stdout 一行 JSON，**必须含 `answer` 字段**（main agent 取它原样作为题目答案提交）。其余字段（per_question / warnings / n 等）供调试。绝不打印解释性文本到 stdout（会污染 JSON）。

- 1_4 `answer` = `"TCxxx,TCyyy,..."`（代码 join，按 test_cases 顺序）。
- 3_3 `answer` = `'["id=>persona|||reply|||action", ...]'`（`json.dumps` 数组文本）。

## 8. 降级 / 不崩原则（照搬 spec_qa）

- 每个子任务独立 try/except，单点失败不拖垮整体（`_answer_one` `:671-728`）。
- 配置缺失 / 检索为空 / 模型失败 → 给保守占位，**保持元素数量/位置不变**（list_equal 元素数、ratio 位置都不能漂）。
- 重试带退避（`spec_qa` 默认 3 次，`min(8.0, 0.5*2**attempt)`）。
- 并发：`ThreadPoolExecutor` 有界并发（spec_qa 默认 4 workers）；3_3 的 30 题 LLM 选源、1_4 的 20 用例可并发，但 **1_4 的写态有顺序依赖**（同 packageId 内状态）——并发会破坏“用例按顺序、状态累积”的语义，**1_4 建议串行执行用例**（或至少同一 packageId 内严格串行）。

## 9. 纯标准库约束

只用 Python 3.9 标准库（`json/os/re/sys/urllib/http.client/sqlite3/zipfile/concurrent.futures/...`）。`requirements.txt` 实际为空（仓库根）。不得引第三方包（requests/httpx 等）。HTTP 一律 `urllib.request` + `http.client` fallback。
