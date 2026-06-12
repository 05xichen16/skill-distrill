# 公开调测集接口文档

## 1. 基本信息

- 服务地址：`http://127.0.0.1:18081`
- 用例文件：`test_cases.json`
- 鉴权配置：`auth_config.json`
- 所有接口请求都需要携带请求头：`X-Package-Id: <packageId>`
- `packageId` 只通过 `X-Package-Id` 请求头传入，不支持通过 Query 参数传入；本地调测时值可以为空，但请求头必须存在。

## 2. 执行规则

- 用例需要按 `test_cases.json` 中出现顺序执行。
- 每个用例是否通过，以接口实际响应与用例断言是否一致为准。
- 如果用例描述包含多个接口动作，需要按描述顺序调用，并校验描述中指定的响应。
- 读接口不需要 `Authorization`。
- 写接口需要先调用 `POST /api/auth/token` 获取 token，并携带 `Authorization: Bearer <accessToken>`。
- 同一个 token 仅允许成功调用 1 次写接口；再次复用同一个 token 调用写接口会返回 401。

## 3. 接口定义

### 3.1 本地调测重置

- 路径：`/api/debug/reset`
- 方法：`POST`
- 请求头：`X-Package-Id: <packageId>`
- 鉴权：不需要 `Authorization`
- 说明：重置当前 `X-Package-Id` 对应的内存运行态数据，不修改 `data_seed.json`。

### 3.2 获取访问令牌

- 路径：`/api/auth/token`
- 方法：`POST`
- 请求头：`Content-Type: application/json`

请求体：

```json
{
  "clientId": "agent_demo_client",
  "clientSecret": "agent_demo_secret"
}
```

### 3.3 查询用户详情

- 路径：`/api/user/detail/{userId}`
- 方法：`GET`
- Path 参数：
  - `userId`：用户 ID
- Query 参数：
  - `verbose`：是否返回详细信息，选填

### 3.4 分页查询用户列表

- 路径：`/api/user/search`
- 方法：`GET`
- Query 参数：
  - `department`：部门，选填
  - `status`：状态，选填，支持 `active` / `inactive`
  - `keyword`：关键字，选填
  - `page`：页码，从 `1` 开始
  - `pageSize`：每页大小，最大值为 `100`
  - `sortOrder`：排序方向，选填，支持 `asc` / `desc`

### 3.5 更新用户信息

- 路径：`/api/user/update`
- 方法：`POST`
- 请求头：
  - `Content-Type: application/json`
  - `Authorization: Bearer <accessToken>`

请求体示例：

```json
{
  "userId": "U1003",
  "email": "u1003.stable@example.com",
  "title": "Senior Engineer"
}
```

### 3.6 删除用户

- 路径：`/api/user/delete/{userId}`
- 方法：`DELETE`
- 请求头：`Authorization: Bearer <accessToken>`

### 3.7 批量更新用户状态

- 路径：`/api/user/batch-update-status`
- 方法：`POST`
- 请求头：
  - `Content-Type: application/json`
  - `Authorization: Bearer <accessToken>`

请求体示例：

```json
{
  "userIds": ["U3001", "U3002"],
  "status": "inactive"
}
```

### 3.8 创建用户备注

- 路径：`/api/user/note/create`
- 方法：`POST`
- 请求头：
  - `Content-Type: application/json`
  - `Authorization: Bearer <accessToken>`

请求体示例：

```json
{
  "userId": "U1007",
  "content": "备注内容"
}
```

### 3.9 查询部门活跃用户统计

- 路径：`/api/user/stat/active`
- 方法：`GET`
- Query 参数：
  - `department`：部门名称
