# Research: 1_4 接口测试结果识别

- **Query**: 摸清 1_4 接口契约——题面/输入文件/服务端点/pass-fail 判定/package_id 用法/输出格式
- **Scope**: mixed（题面+服务源码+实测 18081）
- **Date**: 2026-06-11

## 1. 题面（逐字关键点）

来源 `publish/publish_V1/question.json` id=`1_4`（UTF-8 正确渲染见 /tmp 转储；console 直读为 GBK 乱码）。

- **title**: 接口测试结果识别
- **任务**: 根据输入文件，通过**真实接口调用**完成 `test_cases.json` 中所有用例的验证，判断哪些用例**未通过**。用例需按文件中出现顺序执行；部分用例需连续调用多个接口并校验指定响应。“公开调测用例已做自稳定设计，完整重复执行时失败用例集合应保持一致。”
- **返回格式**: 仅返回**失败用例 ID**，多个 ID 按测试用例顺序用**英文逗号**分隔，不要输出解释。样例输出 `TC000,TC999`。
- **explanation（抗变种关键，逐字要点）** `question.json` 1_4 explanation：
  1. 后续题目可能在公开用例基础上变化接口定义（新增/删除接口、调整路径、请求方式、参数结构、鉴权规则、返回字段结构），也可能同步调整输入数据/接口响应/断言校验要求；
  2. **以实际输入文件中的 api_doc.md、test_cases.json、auth_config.json 和真实接口响应为准，不要直接套用公开样例中的固定接口、固定数据或固定结论**；
  3. 判断时需关注用例之间的**先后影响、连续接口访问关系、鉴权 token 复用规则**，以及返回内容是否完整准确；
  4. 最终结果严格按格式输出；
  5. **同一轮用例验证需保持同一个 X-Package-Id**，服务按 packageId 保留删除/状态变更/标签/备注/归档等运行态数据，后续查询统计以当前 packageId 真实状态为准。

判分：`type=ratio`，`score=2`，参考答案 `TC009,TC011,TC014,TC015,TC016,TC020`（来源 `question_disc.json`；**仅供理解格式，不得硬编码进 skill**）。ratio 语义见 `grading-semantics.md`。

## 2. 输入文件（files 列表）

题面 `files`: `./测试用例接口文档/api_doc.md`、`./测试用例接口文档/test_cases.json`、`./测试用例接口文档/auth_config.json`。实际路径在 `publish/publish_V1/测试用例接口文档/`。

### test_cases.json — `publish/publish_V1/测试用例接口文档/test_cases.json`

20 条用例（TC001..TC020），每条结构：

```json
{ "id": "TC001",
  "description": "<中文动作描述，可能含多步>",
  "assert": {
    "expectedStatus": 200,
    "expectedFields": ["code", "data.userId", "data.email", "data.title"],   // 点路径
    "expectedValues": { "code": 0, "data.userId": "U1003", ... }             // 点路径 -> 期望值
  } }
```

- `description` 是**自然语言**（中文），描述要调哪些接口、用什么参数、最后校验哪一次响应。skill 必须把 description 翻成实际 HTTP 调用（靠 LLM 解析 + api_doc 对路径/参数对照）。
- `expectedFields`：被校验响应里**必须存在**的字段（点路径，如 `data.list.0.userId`、`data.manager.name`）。字段缺失 = 不通过（这是 TC014 失败的机理）。
- `expectedValues`：点路径 -> 期望值，逐一**精确相等**判定。
- `expectedStatus`：HTTP 状态码（如 TC010 期望 404）。

### api_doc.md — `publish/publish_V1/测试用例接口文档/api_doc.md`

公开端点文档（**可能在变种里改**，要以实际文件为准）。要点：
- 服务 `http://127.0.0.1:18081`；所有请求必带 `X-Package-Id: <packageId>`（仅 header，不支持 query）。
- 用例按出现顺序执行；多动作用例按描述顺序调用并校验描述指定的响应。
- 读接口不需 `Authorization`；写接口需先 `POST /api/auth/token` 拿 token 并带 `Authorization: Bearer <accessToken>`。
- **同一 token 仅允许成功调用 1 次写接口；再次复用同一 token 调写接口返回 401**。
- 文档列出端点：`/api/debug/reset`(POST)、`/api/auth/token`(POST)、`/api/user/detail/{userId}`(GET, query `verbose`)、`/api/user/search`(GET, query `department/status/keyword/page/pageSize/sortOrder`)、`/api/user/update`(POST)、`/api/user/delete/{userId}`(DELETE)、`/api/user/batch-update-status`(POST)、`/api/user/note/create`(POST)、`/api/user/stat/active`(GET, query `department`)。

### auth_config.json — `publish/publish_V1/测试用例接口文档/auth_config.json`

```json
{ "baseUrl": "http://127.0.0.1:18081",
  "packageIdHeader": "X-Package-Id",
  "token": { "endpoint": "/api/auth/token", "method": "POST",
             "headers": {"Content-Type": "application/json"},
             "body": {"clientId": "agent_demo_client", "clientSecret": "agent_demo_secret"},
             "responseTokenPath": "data.accessToken",
             "authorizationHeaderFormat": "Bearer ${accessToken}" },
  "usage": { "readApis": "读接口不需要 Authorization，但仍需要携带 X-Package-Id。",
             "writeApis": "写接口需要同时携带 X-Package-Id 和 Authorization。",
             "tokenReuseRule": "同一个 token 仅允许成功调用 1 次写接口；再次调用写接口需要重新获取 token，除非用例明确要求复用旧 token 并校验 401 响应。" } }
```

skill 应**从此文件读取** token endpoint / body / `responseTokenPath` / header 格式，而不是写死，以抗变种。

## 3. 服务契约（源码 + 实测）

源码 `publish/publish_V1/00 题目试做前需要先启动服务/1_4接口服务/public_mock_service.py`；初始数据 `.../1_4接口服务/data_seed.json`（启动读一次，写操作只改内存）。README `.../1_4接口服务/README.md`。

### 端口 / 数据集

- 端口 18081 → `case_set = "public_root"`（`public_mock_service.py:27-29`, `:801`）。`SERVICE_VERSION="2.3"`。
- `/health` 返回 `data.caseSet=public_root` 等（`:313-328`）。实测确认服务在线。
- 内存按 packageId 隔离（`RuntimeStore.by_package`，`:42-63`）。`/api/debug/reset` 重置当前 packageId（`:237-244`，仅本地调测）。

### package_id 规则（`package_id_from` `:167-187`）

- 所有业务接口必须带 `X-Package-Id` header（**header 必须存在**）。缺失 → `400 {"code":40002,"message":"missing X-Package-Id header"}`（实测确认）。
- header 值可空：空值映射到 `default_package_id()` = 环境变量 `packageId` / `PACKAGE_ID` / `"local_default"`（`:90-91`）。**正式赛平台传真实 packageId**。
- **skill 要点**：一次运行内对 18081 的所有请求必须用**同一个 X-Package-Id**（题面第 5 条），否则删除/状态变更等运行态丢失，连续用例判错。建议直接用环境注入的 `PACKAGE_ID`/`packageId`（与模型 header 一致）。

### 鉴权 / token（单次写）

- `POST /api/auth/token`（需 X-Package-Id）→ `200 {"data":{"accessToken":"token_public_root_<pkg>_<n>","expiresIn":300}}`（`:250-252`, `issue_token :65-71`）。
- 写接口先 `consume_write_token`（`:73-83`）：`Authorization` 须 `Bearer <token>`；token 剩余次数初始 1，成功一次后置 0；**第二次同 token 写 → `401 {"code":40101,"message":"token expired"}`**（实测确认 `write2-sametoken → 401`）。读接口不校验 token。
- 写端点集合 `WRITE_ENDPOINTS`（`:30-39`）：update / batch-update-status / note/create / update-status / tag/add / transfer-department / update-manager / batch-transfer-department；另有 DELETE 路由 delete/{id}、note/delete/{id}（`:297-305`）。
- **skill 要点**：每个需要写的用例步骤，**调用前先取一个新 token**（除非用例明确要测 401 复用）。

### 全部端点（do_POST/do_DELETE/do_GET 路由）

- POST: `/api/debug/reset`, `/api/auth/token`, `/api/user/update`, `/api/user/batch-update-status`, `/api/user/note/create`, `/api/user/update-status`, `/api/user/restore-status/{id}`, `/api/user/note/delete/{id}`, `/api/user/archive/{id}`, `/api/user/restore/{id}`, `/api/user/tag/add`, `/api/user/transfer-department`, `/api/user/update-manager`, `/api/user/batch-transfer-department`（路由表 `:263-276`）。
- DELETE: `/api/user/delete/{id}`, `/api/user/note/delete/{id}`（`:297-305`）。
- GET: `/health`, `/api/user/detail/{id}`(query verbose), `/api/user/note/list/{id}`, `/api/user/tag/list/{id}`, `/api/user/search`, `/api/user/stat/active`, `/api/user/stat/tag`, `/api/user/stat/department`, `/api/user/stat/department-summary`, `/api/user/stat/manager`（`:309-373`）。
- 标准响应包：`{"code":0,"message":"ok","data":...}`（`ok()` `:94-95`）；not_found `404 {"code":1004,"message":"user not found","data":null}`（`:98-99`）；bad_request `400 {"code":40001,...}`。

### pass/fail 如何判定（skill 侧自行实现，服务不判分）

服务**只返回真实响应**，是否 pass 由 skill 按 `test_cases.json` 的 assert 判定：
1. 实际 HTTP 状态码 == `assert.expectedStatus`；
2. `assert.expectedFields` 中每个点路径在响应里**存在**；
3. `assert.expectedValues` 中每个点路径的实际值 == 期望值（精确相等）。
任一不满足 → 该用例**失败**，收集其 ID。

### 公开用例为何失败（机理，**抗变种用，禁止硬编码 ID**）

逐条对照源码 `handle_*` 与实测确认，6 个失败用例都是服务**故意制造的 mismatch**（`public_root` 分支）：

- **TC009** U1010 `verbose=true` 期望 `manager.name=ManagerA`；服务 `handle_detail` 对 public_root U1010+verbose 返回 `manager={"userId":"M9001","name":"WrongManager"}`（`:404-405`，实测确认 name=WrongManager）→ 值不等 → 失败。
- **TC011** mobile `activeCount` 期望 64；`handle_stat_active` 对 public_root mobile 返回 `activeCount=63`（`:633-634`，实测确认 63）→ 失败。
- **TC014** U1004 期望 `data.title=Engineer`；`handle_detail` 对 public_root U1004 执行 `result.pop("title")`（`:402-403`，实测响应无 title 字段）→ 字段缺失 → 失败。
- **TC015** status=active `sortOrder=desc` 期望 `list.0.userId=U2240`；search 生成升序 U2001..U2240 且 `paginate` 不按 sortOrder 反转，`list[0]=U2001`（`:433-436`, paginate `:199-202`）→ 失败。
- **TC016** status=inactive `sortOrder=desc` 期望 `list.0.userId=U9009`；服务 `first="U9008" if desc else "U9001"`（`:444-446`），total=9 对但首条=U9008 → 失败。
- **TC020** U1005 期望 `title=Quality Owner`；无任何写把 U1005 title 改成此值，seed title=Engineer（`data_seed.json`）→ 失败。

通过的用例（TC001-008,010,012,013,017-019）依赖 seed 初值 + 正确的写后读（如 TC001 update U1003 后 detail 命中，TC005 batch-update U3001/U3002 → updatedCount=2/failedCount=0），且每个写步骤需新 token。

**关键**：失败原因是“真实响应 ≠ 断言”，skill 必须**真调接口拿响应再比断言**，而不是预测。变种会改服务/数据/断言，硬编码 ID 必死。

## 4. skill 实现路径（1_4）

skill「`interface_test`」应做：

1. 从 `_runtime`/参数定位 `测试用例接口文档/` 目录，读 `test_cases.json` / `api_doc.md` / `auth_config.json`。
2. baseUrl、packageIdHeader、token 配置从 `auth_config.json` 读（不写死）。X-Package-Id 用环境注入的 `PACKAGE_ID`/`packageId`（整轮固定一致）。
3. 按 `test_cases.json` **出现顺序**逐条执行。对每条：
   - 用 LLM 把 `description` 解析成有序 HTTP 步骤（method/path/query/body），对照 `api_doc.md` 校正端点与参数；区分读/写。
   - 写步骤：调用前 `POST /api/auth/token` 取新 token，带 `Authorization: Bearer`。（除非 description 明确要求复用旧 token 测 401。）
   - 执行所有步骤；按 description 指定（默认最后一次）拿到**被校验响应**。
4. 用 `assert`（status + expectedFields 存在性 + expectedValues 精确相等，点路径解析）判 pass/fail。失败则记 ID。
5. 输出失败 ID，**按 test_cases 顺序、英文逗号拼接**（在代码里 join，保证顺序与位置；ratio 位置敏感）。`answer` = 该字符串。
6. 纯标准库 `urllib`/`http.client` 调 18081；LLM 调用复用模板（见 `skill-template-notes.md`）。

潜在难点 / 风险：
- description→HTTP 的解析靠 LLM，可能出错；建议让 LLM 输出结构化步骤 JSON，代码再执行+断言（断言判定放代码里，确定性强）。
- 多步用例的“校验哪一次响应”需 LLM 判断（题面：校验描述中指定的响应，默认最后一次）。
- ratio 位置敏感：**宁可严格按 assert 判，不要主观补漏**；多报一个 ID 会让其后所有位置错位，伤害比漏报更大。
- token 单次写：每个写步骤都要新 token，否则连续写第二步 401 导致后续状态没生效、读用例误判。
- 整轮固定 X-Package-Id：否则运行态丢失。
