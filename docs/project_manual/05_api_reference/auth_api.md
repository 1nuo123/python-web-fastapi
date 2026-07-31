# 鉴权 API

## 1. 范围与源码

本模块提供用户名密码登录、refresh token 轮换、token session 吊销和当前主体自省。

| 源码 | 职责 |
| --- | --- |
| `src/api/endpoint_auth_access/route_auth_access.py` | 4 个 route、同步桥接、认证失败安全事件。 |
| `src/api/endpoint_auth_access/contract_auth_access.py` | 3 个请求模型及字段限制。 |
| `src/application/issue_access_token_usecase.py` | 登录、密码 rehash、token session 落库。 |
| `src/application/refresh_access_token_usecase.py` | refresh 轮换、重放吊销和双维度节流。 |
| `src/application/revoke_access_token_usecase.py` | session 吊销与幂等返回。 |
| `src/core/auth_contract/token_payload_contract.py` | token 响应与 JWT payload 契约。 |

## 2. 端点总表

| 方法 | 路径 | 请求 | `data` | Route 级 Bearer |
| --- | --- | --- | --- | --- |
| POST | `/auth/token` | `TokenIssueRequest` | `TokenIssuePayload` | 否 |
| POST | `/auth/refresh` | `TokenRefreshRequest` | `TokenIssuePayload` | 否 |
| POST | `/auth/revoke` | `TokenRevokeRequest` | `TokenRevokePayload` | 否 |
| GET | `/auth/me` | 无 | `AuthenticatedPrincipal` | 是 |

`/auth/revoke` 不要求另一个 access token；refresh token 本身是吊销凭据。4 个响应均由外层 `ResponseEnvelope[T]` 包装。

## 3. 请求契约

三个 body model 都设置 `extra="forbid"`，未知字段返回 `422 system.request.invalid`。

| 请求 | 字段 | 精确约束 |
| --- | --- | --- |
| `TokenIssueRequest` | `username` | string，原始长度 1..128；validator 去首尾空白，结果不得为空。归一化后的值传入登录与失败审计。 |
| `TokenIssueRequest` | `password` | string，长度 1..256；不做 trim。 |
| `TokenRefreshRequest` | `refresh_token` | string，长度 16..4096，正则 `^[A-Za-z0-9._~+/=-]+$`。 |
| `TokenRevokeRequest` | `refresh_token` | 与 refresh 请求相同。 |
| `/auth/me` | `Authorization` | `Bearer <access_token>`；refresh token 因 `token_use` 不匹配而无效。 |

请求体还受全局 `runtime.web.max_request_body_bytes` 约束，超限为 `413 system.request.payload_too_large`。

## 4. 响应契约

### 4.1 token 签发/刷新

`TokenIssuePayload`：

| 字段 | 类型/值 |
| --- | --- |
| `kind` | 固定 `token_issue` |
| `schema_version` | 固定 `1.1` |
| `access_token` | JWT access token 原文 |
| `refresh_token` | JWT refresh token 原文 |
| `token_type` | 固定 `Bearer` |
| `expires_in_seconds` | access token 有效期 |
| `refresh_expires_in_seconds` | refresh token 有效期 |

### 4.2 吊销

`TokenRevokePayload` 为 `kind=token_revoke`、`schema_version=1.1`、`revoked: bool`、`revoked_at_epoch: int`。当前成功路径总是 `revoked=True`；重复吊销同一现存会话复用第一次的时间。

### 4.3 当前主体

`AuthenticatedPrincipal` 为 `kind=authenticated_principal`、`schema_version=1.0`，并包含 `subject_id`、`username`、`roles[]`、`scopes[]`、`is_admin`。`is_admin` 由是否包含 `admin` role 派生；拥有业务角色的普通用户可访问 `/auth/me`，但不能因此访问后台 API。

## 5. 登录语义

1. 先按 username 执行认证失败节流断言。
2. 同一数据库事务读取身份、校验状态/密码、按需升级密码 hash、签发 token pair 并写 refresh session。
3. 用户不存在、用户停用、密码错误统一返回 `401 auth.access.invalid_credentials`，并累计同一 username 的失败次数。
4. commit 成功后清除失败计数。
5. route 对 `invalid_credentials/request_throttled` 记录摘要化的登录失败/限流安全事件；risk control 启用且识别密码喷洒时追加 `auth_password_spray_suspected` 事件。用户名、IP、User-Agent 以 digest 记录。

登录时“停用”刻意不返回 `account_disabled`，避免暴露账号存在性。

## 6. refresh 轮换语义

1. client IP 由可信代理策略下的 `ClientIpResolver` 解析，不直接信任任意 `X-Forwarded-For`。
2. 同时检查 `refresh_token|ip:<resolved_ip>` 与 `refresh_token|global` 节流主体。
3. 事务外按 `TokenUse.REFRESH` 解码；解码失败累计两个主体的失败计数。
4. 事务内 `SELECT ... FOR UPDATE` 读取 token id，并核对 subject、session id、rotated/revoked 状态和当前身份。
5. 正常轮换沿用 `token_session_id`；先写新 refresh 行，再把旧行标记为 rotated/revoked。
6. 旧 token 已轮换时视为重放，吊销整个 session 后单独 commit，再返回 `401 auth.token.reused`。
7. 成功 commit 后才清除两个刷新失败计数。

route 对 refresh 的 `HttpFaultException` 发安全事件：重放映射为 `auth_refresh_reused`，其他 fault 以 `auth_token_invalid` 事件类型记录，token/IP/User-Agent 只写 digest。

## 7. 吊销与 access token 即时失效

- revoke 验证 refresh JWT、数据库记录、subject 和 session id；不存在/不匹配为 `401 auth.token.invalid`。
- 吊销作用于整个 `token_session_id`，不是只改当前 refresh token 行。
- access token 中虽然携带 roles/scopes，受保护请求仍读取当前身份授权真值；用户停用、密码重置或角色替换导致 refresh sessions 吊销，并可使存量 access token 在中间件校验时立即失效或失去权限。
- revoke 当前没有登录/refresh 那样的失败节流和专用 route 失败审计。

## 8. 错误码

| HTTP | 错误码 | 端点与触发条件 |
| --- | --- | --- |
| 400/422 | `system.request.invalid` | JSON/Pydantic 请求不满足契约；通常验证错误由 presenter 返回 422。 |
| 401 | `auth.access.invalid_credentials` | `/auth/token` 用户名、状态或密码失败。 |
| 403 | `auth.access.account_disabled` | refresh 或 `/auth/me` 对应主体已停用。 |
| 401 | `auth.token.invalid` | 签名/格式/用途错误，session 记录不存在，subject/session 不匹配。 |
| 401 | `auth.token.expired` | access 或 refresh token 过期。 |
| 401 | `auth.token.revoked` | refresh token session 已吊销，或受保护请求发现 session 吊销。 |
| 401 | `auth.token.reused` | 已轮换 refresh token 被再次使用。 |
| 429 | `auth.request.throttled` | 登录 username 或 refresh IP/global 维度超阈值。 |
| 413 | `system.request.payload_too_large` | body 超全局上限。 |
| 503 | `system.resource.not_ready` | 认证所需数据库/缓存/runtime 未就绪。 |

## 9. 使用示例

```json
{
  "username": "admin",
  "password": "<password>"
}
```

```http
Authorization: Bearer <access_token>
```

客户端应把 refresh token 当作一次性轮换凭据：refresh 成功后原子替换本地 token pair；若得到 `auth.token.reused`，应清除整个本地会话并重新登录。

## 10. 事实核验测试

| 测试 | 覆盖事实 |
| --- | --- |
| `test/interface_test/test_http_interface.py` | token/refresh/revoke/me、过期和 OpenAPI principal。 |
| `test/interface_test/test_security_http_interface.py` | 登录与访问认证行为。 |
| `test/interface_test/test_rate_limit_http_interface.py` | 登录限流。 |
| `test/interface_test/test_security_event_http_interface.py` | 登录/refresh 安全事件。 |
| `test/contract_test/test_refresh_token_invalidation_contract.py` | refresh session 失效契约。 |
| `test/integration_test/admin_identity/test_admin_identity_rbac_integration.py` | 身份变更后的 refresh session 吊销。 |
| `test/path_test/test_runtime_path.py` | 端到端认证运行路径。 |

## 11. 相关文档

- [领域模型与常量](../03_application_domain/domain_model_and_constants.md)
- [应用用例](../03_application_domain/application_usecases.md)
- [API 总览](api_overview.md)
