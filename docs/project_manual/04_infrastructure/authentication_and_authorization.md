# 鉴权与授权

## 1. 这是什么

详解认证授权基础设施的全部组件：JWT 令牌服务（含密钥环签名）、密码哈希、OAuth2 提取、失败节流、认证绑定中间件、授权守卫与 bootstrap admin。覆盖"令牌怎么签、怎么验、权限怎么判、暴力破解怎么防"。

**最后更新范围**：覆盖 `src/infrastructure/auth/` 6 个文件、认证中间件、`AuthorizationGuard`、领域授权策略与 auth_runtime 配置。

## 2. 令牌模型

- **双令牌 + 会话**：登录颁发 access token（默认短效）与 refresh token（长效），二者共享一个 `token_session_id`（sid claim）。刷新令牌会话持久化在 `auth_refresh_token` 表；access token 无状态但其会话必须活着。
- **JWT claims**：`jti`（token_id）、`sid`（会话）、`sub`（subject_id）、`username`、`roles`、`scopes`、`token_use`（access/refresh）、`iat/exp/iss/aud`、`kind/schema_version`（契约标识）。
- **签名**：`JwtTokenService` 默认用配置的 `jwt_secret + jwt_algorithm`；密钥管理启用时按 `jwt_signing` 密钥族取活跃密钥签名并写 `kid` 头，验签按 kid 取对应密钥——支持密钥轮换期间新旧并存。
- **解码校验**：签名、exp（可传 current_epoch 保证同一请求内时钟一致）、iss/aud、`token_use` 与预期一致、payload 结构契约校验；任何失败归一化为 401 `auth.token.invalid/expired`。

## 3. 刷新令牌轮换与重放防御

`refresh_token_rotation_enabled` 被配置模型强制为 true。每次刷新：旧令牌行 `FOR UPDATE` 加锁 → 五重校验 → 新令牌对沿用同一 sid 落库 → 旧行标记 `rotated_to_token_id` + `revoked_at`。

**重放检测**：旧刷新令牌再次使用（`rotated_to_token_id` 已存在）判定为令牌泄漏信号，立即吊销整个 token_session（`revoke_token_session`）并独立 commit（不随后续 rollback 撤销），返回 401 `auth.token.reused`。攻击者与合法用户都被登出，爆炸半径 = 单会话。

吊销（`/auth/revoke`）幂等：重复吊销复用原 `revoked_at`。

## 4. 认证（AuthN）链路

见[中间件链](../02_backend/middleware_chain.md) 3.3。要点回顾：Bearer 解码后**每请求查库**重建授权快照（roles/scopes 取数据库当前值，非令牌快照）并校验令牌会话状态（存在/主体一致/未吊销/未过期/一致性）。因此：

- 管理员改用户权限/禁用账号 → 该用户所有存量令牌下一请求即生效。
- 代价是每认证请求一次索引查询——通过线程池桥接与连接池承载，属于有意的"安全>性能"取舍。

可选 Token-IP 绑定（`token_binding` 策略，默认关闭）：对指定路径/token_use 的令牌绑定首个使用 IP 的摘要（TTL 内），换 IP 即 401 并发安全事件，适用于高风险后台端点。

## 5. 授权（AuthZ）链路

- 事实源：`src/domain/auth/admin_route_authorization_policy.py` 的 14 个 `RouteAuthorizationRequirement`（角色 + scope 集合）。
- 断言点：路由守卫 → `DependencyContextAccessor.read_authorized_principal(request, requirement)` → `AuthorizationGuard.assert_requirement` → `AuthorizationPolicyEvaluator.evaluate`（纯函数：required_roles ⊆ principal.roles 且 required_scopes ⊆ principal.scopes）。
- 失败：403 `auth.authorization.permission_denied` + `authorization_denied` 安全事件（含 subject、reason、状态码）。
- RBAC 数据模型：user —(auth_user_role)— role —(auth_role_scope)— scope，三实体 + 两关联表；用户的有效 scope = 其全部角色的 scope 并集。

## 6. 失败节流（AuthFailureThrottle）

以 `CacheService`（AUTH_THROTTLE 命名空间）为存储的计数+锁定模型，两通道独立配置：

| 通道 | 键主体 | 配置（runtime.auth） |
| --- | --- | --- |
| issue_access_token | username（哈希后入键） | `issue_access_token_failure_limit / _window_seconds` |
| refresh_access_token | `refresh_token\|ip:<client_ip>` 与 `refresh_token\|global` 双维度 | `refresh_access_token_failure_limit / _window_seconds` |

窗口内失败次数达到 limit → 写锁定键（TTL=`throttle_lock_seconds`）→ 后续请求直接 429 `auth.request.throttled`（不再查库）。成功后清计数。**用户名不存在也计数**——外部行为与密码错误一致，防账号枚举。生产要求分布式缓存承载（内存缓存被启动器禁止），保证多实例共享节流状态。

## 7. 密码哈希与 bootstrap admin

- `PasswordHasher`：argon2（配置枚举当前仅 argon2）；`needs_rehash` 支持参数升级——登录成功且哈希参数过时则同事务重哈希。
- 初始管理员两条路径：
  - **CLI（生产唯一方式）**：`python -m src.cli.create_initial_admin`，交互/参数式创建，密码经 `AUTH_BOOTSTRAP_ADMIN_PASSWORD` 注入。
  - **配置引导（仅非生产）**：`modules.auth.bootstrap_admin.enabled=true` 时启动器执行 `BootstrapAdminSynchronizer.synchronize`（按 subject_id 幂等 upsert 用户+角色绑定）；生产环境启用直接拒绝启动。

## 8. 配置项（runtime.auth）

`jwt_secret`（SecretStr，生产强制外部注入）、`jwt_algorithm`、`access/refresh_token_expires_in_seconds`、`issuer`、`audience`、`password_hash_algorithm`、`refresh_token_rotation_enabled`（必须 true）、两组节流参数、`throttle_lock_seconds`。全部为正整数校验，见 `config/runtime/auth_runtime/*.toml`。

## 9. 注意事项

- 令牌内 roles/scopes 只能用于展示（如 `/auth/me`），服务端判断一律走数据库快照；不要在新代码里信任 claim 做授权。
- `decode_token` 的 `current_epoch` 参数用于把"解码校验"与"业务时间"钉在同一时刻，刷新链路必须传，避免边界时刻的不一致。
- JWT_SECRET 轮换（无密钥管理时）会使全部存量令牌立即失效；启用密钥管理密钥族轮换则平滑过渡。
- 修改令牌 payload 结构需同步 `token_payload_contract.py` 的 kind/schema_version 与 contract 测试。

## 10. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_jwt_token_service_unit.py` | 签发/解码/kid 轮换。 |
| unit | `test/unit_test/test_auth_failure_throttle_unit.py` | 节流窗口与锁定。 |
| unit | `test/unit_test/test_auth_persistence_unit.py` | 轮换/重放/吊销语义。 |
| interface | `test/interface_test/test_security_http_interface.py` | 401/403/429 表面行为。 |
| integration | `test/integration_test/test_auth_rbac_integration.py` | 真实库 RBAC 与令牌链路。 |

## 11. 相关文档

- [项目文档总览](../README.md)
- [鉴权 API](../05_api_reference/auth_api.md)
- [领域模型与常量](../03_application_domain/domain_model_and_constants.md)
- [安全防护](security_protection.md)
- [安全维护](../10_maintenance/security_maintenance.md)
