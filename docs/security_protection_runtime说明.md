# 安全防护运行时说明

> 修订时间：2026-07-20。审计关键事件即时落库语义与 `src/infrastructure/logging/log_buffer_dispatcher.py` 最终实现对齐；文档与源码冲突时以源码为准。

## 已落地能力

- `runtime.security.detail.protection`：统一承载流控、风险控制、IP 封禁、Token-IP 绑定和出站 URL 安全策略。
- `runtime.distributed_lock`：独立分布式锁运行时入口，当前通过缓存 Store 提供 `set-if-absent`、owner 校验释放能力；缓存或 Redis 不可用时固定 fail-closed。
- `runtime.key_management`：统一密钥管理运行时入口，提供密钥族初始化、密钥环快照、当前密钥读取、按 key id 读取和轮转兼容窗口。
- IP 封禁链路：先查强类型 `IpBlockCacheEntry` 缓存，未命中查数据库，命中后回填缓存；释放封禁时同步删除缓存。缓存命中时按 `blocked_until_epoch` 动态计算 `Retry-After`，不超过真实剩余封禁时间。
- 限流链路：`RateLimitMiddleware` 在请求入口执行流控，支持默认策略与 path/method 策略集合，超限返回 `429` 和 `Retry-After`。限流首次超限并触发封禁仍记录 `rate_limit.blocked`；已封禁 IP 后续命中记录为 `ip_block`。
- 安全事件链路：认证失败、认证节流、密码喷洒疑似、refresh token 复用、限流、请求体过大、Token-IP 不匹配、SSRF 拦截等事件通过统一 `SecurityEventEnvelope` 写入现有结构化日志链路。
- 审计关键事件即时落库：`admin.identity.changed`（含用户/scope/role 变更与配置热更新 `settings_reload`）与 `config.security_rejected` 两类事件在 `LoggingResourceFacade.emit_security_event()` 中被标记为 `persistence_priority = audit_critical`。`LogBufferDispatcher.emit()` 对该优先级绕过 lazy-flush 缓冲，在发射线程内以 `reason="audit_critical"` 同步提交数据库写请求，emit 返回前事件已进入事务提交路径，进程被强制终止不丢失窗口内审计事件（由 `test_audit_crash_safety_integration.py` 故障注入验证）。
- 审计写失败降级：审计关键写失败时按 `fallback_to_stdout` 配置由 `DatabaseLogWriter` 执行脱敏后的 stdout 保底输出，同时写入独立内部 logger，并累计到 `AuditWriteFailureCounter` 只读快照（`failed_count`、`pending_items`），经指标桥接暴露为 `fastapi_log_buffer_flush_total{reason="audit_critical",failed="true"}`，配套告警规则 `audit_critical_write_failure`。
- 安全事件指标：`emit_security_event()` 同点位挂接 `fastapi_security_event_total{event_type,decision,severity}` 低基数指标，标签执行 `SecurityEventType` 封闭枚举白名单，不属于白名单的事件类型不打点。
- 客户端 IP 事实源：`ClientIpResolver` 是应用内唯一客户端 IP 解析入口。base/test 默认可信任 loopback 代理来源；production 默认不信任任何代理头，必须显式声明真实代理 CIDR 后才读取 `Forwarded` / `X-Forwarded-For`，非可信来源忽略伪造转发头并回退到连接来源 IP。
- SSRF 防护：共享同步/异步 HTTP client 发起请求前校验 URL，并在连接层固定解析 IP、校验真实 peer IP，拒绝本机、私网、link-local、reserved、metadata、非 global 地址、peer 缺失和 peer mismatch。
- 管理入口：`security_protection` 模块是安全控制面能力；`/security/ip-blocks` 的查询、创建、详情和释放接口统一走 `RequestExecutionBridge` 与管理员安全 IP 封禁用例，路由层只保留请求契约、鉴权和响应封装。

## 配置入口

### runtime.security

- `flow_control.enabled`：是否启用通用流控。
- `flow_control.default_limit`：默认窗口内允许请求数。
- `flow_control.default_window_seconds`：默认窗口秒数。
- `flow_control.fail_mode`：缓存故障失败模式，固定为 `fail_closed`。
- `flow_control.policies[]`：限流策略集合，当前默认包含 `auth_token` 与 `auth_refresh`，字段为 `header.policy_name`、`detail.path`、`detail.method`、`detail.limit`、`detail.window_seconds`、`detail.key_dimensions`、`detail.block_when_exceeded`、`detail.block_seconds`。
- `risk_control.enabled`：是否启用认证风险信号。
- `risk_control.password_spray_limit`：单 IP 登录失败达到该阈值时记录密码喷洒疑似事件。
- `risk_control.password_spray_window_seconds`：认证风险信号统计窗口。
- `ip_block.enabled`：是否启用 IP 封禁策略。
- `ip_block.cache_ttl_seconds`：封禁缓存 TTL。
- `ip_block.default_block_seconds`：自动封禁时长。
- `client_ip_resolver`：当前由基础设施统一装配，不在本轮暴露独立 TOML 配置；base/test 默认可信代理集合为 loopback，production 默认可信代理集合为空，部署在外部代理后必须由网关层与运行时配置共同声明可信代理边界。
- `token_binding.enabled`：Token-IP 绑定开关，默认关闭。
- `token_binding.applicable_paths`：Token-IP 绑定适用路径，默认仅声明 `/auth/me`。
- `token_binding.token_uses`：Token-IP 绑定适用 token 用途，默认 `access`。
- `outbound_url_safety.enabled`：SSRF 校验开关。
- `outbound_url_safety.allowed_schemes`：允许的出站协议。
- `outbound_url_safety.deny_private_networks`：是否拒绝私网、本机、link-local、reserved 与非 global 地址。
- `outbound_url_safety.deny_metadata_address`：是否拒绝 `169.254.169.254`。
- `outbound_url_safety.deny_cidr_blocks`：额外拒绝的 CIDR 清单，production 默认包含 `169.254.0.0/16`。
- `outbound_url_safety.deny_hostnames`：额外拒绝的主机名清单，production 默认包含云 metadata 主机名。
- `outbound_url_safety.allowed_hostnames`：目的域名允许清单；主机名加载时会去除首尾空白并转为小写，禁止空白项。
- `outbound_url_safety.enforce_allowed_hostnames`：是否强制目的域名允许清单；production 默认启用，空清单表示不允许任何未显式声明的出站目的域名。

### runtime.distributed_lock

- `header.enabled`：分布式锁基础设施开关。
- `detail.backend`：锁后端，当前使用缓存 Store。
- `detail.lease_seconds`：默认租约时长。
- `detail.wait_seconds`：默认等待时长。
分布式锁故障策略固定为 fail-closed。旧 `detail.failure_mode` 已不再是运行时契约字段，不能作为可配置能力依赖。

### runtime.key_management

- `header.enabled`：密钥管理基础设施开关。
- `detail.backend`：密钥管理后端，当前使用缓存 Store。
- `detail.key_families`：托管密钥族列表，包含用途、状态、当前 key id、是否启用、轮转策略、有效密钥数量和旧密钥兼容窗口。
- `detail.key_families[].rotation_policy.compatibility_window_seconds`：旧 key 兼容窗口，轮转后旧 key 在窗口内仍可按 key id 读取，用于 JWT 验签等场景。

## 安全事件矩阵

| 事件类型 | 当前接入路径 | 敏感字段处理 |
|---|---|---|
| `auth.login.failure` | `/auth/token` 凭证失败 | username、IP、User-Agent 只记录摘要 |
| `auth.login.throttled` | `/auth/token` 认证节流 | username、IP、User-Agent 只记录摘要 |
| `auth.password_spray_suspected` | 登录失败风险信号 | username、IP、User-Agent 只记录摘要 |
| `auth.refresh.reused` | `/auth/refresh` 旧刷新令牌复用 | refresh token 只记录摘要 |
| `auth.token.invalid` | `/auth/refresh` 无效刷新令牌 | refresh token 只记录摘要 |
| `rate_limit.blocked` | 通用限流超限或首次触发封禁 | IP 只记录摘要 |
| `ip_block` | 已封禁 IP 命中拦截 | IP 只记录摘要，事件包含封禁原因、状态、解封时间和 retry_after |
| `payload.too_large` | 请求体大小保护 | 不记录请求体 |
| `token_binding.mismatch` | Token-IP 绑定不匹配 | token 与 IP 只记录摘要 |
| `ssrf.blocked` | 出站 HTTP URL 安全钩子与连接层 peer 校验 | host 只记录摘要，不记录完整 URL 查询串；host 不可用时写哨兵摘要 |
| `admin.identity.changed` | 管理员用户/scope/role 变更与配置热更新（审计关键，即时落库） | 仅记录操作名、目标类型/标识与操作者主体标识 |
| `config.security_rejected` | 配置热更新安全校验拒绝（审计关键，即时落库） | 仅记录拒绝原因码与被拒字段数量 |

## 管理链路

- `SecurityProtectionRouteCatalog` 中的 `list_ip_blocks`、`create_ip_block`、`get_ip_block`、`release_ip_block` 均通过 `DEFAULT_SYNC_REQUEST_EXECUTION_NAME` 对应的 `RequestExecutionBridge.run_sync()` 执行。
- 应用层用例依赖 `AdminSecurityIpBlockRuntimePort`，返回 `SecurityIpBlockRecordSnapshot`，不直接导入基础设施 ORM 或仓储实现。
- 创建和释放封禁时，基础设施端口负责调用 `IpBlockGuard`、同步缓存、提交数据库事务，并通过 `SecurityEventBuilder.build_ip_block_event_from_scope()` 写入安全事件。
- `system_overview` 与 `security_protection` 均使用中心化后台授权 requirement；manifest 中的 `admin_boundary_policy` 会与授权 requirement 做一致性校验。

## 排障入口

- 限流误拦截：检查 `runtime.security.detail.protection.flow_control` 阈值和窗口。
- IP 封禁误拦截：通过受控管理员入口 `/security/ip-blocks*` 查询 `ip_digest`、封禁状态和过期时间。若响应 `Retry-After` 异常，应检查缓存中的 `IpBlockCacheEntry.blocked_until_epoch` 是否与数据库 active 记录一致。
- 分布式锁异常：检查缓存后端可用性、锁租约 TTL、owner 校验释放语义。
- 密钥管理异常：检查 `runtime.key_management` 密钥族是否启用，缓存后端是否可读写，`current_key_id` 是否仍在有效 key 集合中。
- 密钥轮转异常：检查 `runtime.distributed_lock.detail.lease_seconds` 与 `wait_seconds` 是否足够覆盖轮转事务，检查旧 key 是否仍处于 `compatibility_window_seconds`；分布式锁故障会固定按 fail-closed 中断关键路径。
- 缓存回填异常：IP 封禁缓存 miss 后会查数据库 active 记录并回填，回填 TTL 不超过数据库 `blocked_until_epoch`。
- SSRF 误拦截：检查 URL host 解析结果、目的域名允许清单、私网策略、metadata 地址策略、固定解析 IP 与连接后的 peer IP。
- DNS 重绑定边界：当前同步/异步出站客户端已经在 transport 层固定解析结果并校验连接后的 peer IP；redirect/retry 会重新执行同一策略。若业务改用非共享 HTTP client，需要显式接入同一 transport 或出站代理。
- 安全事件排查：查看结构化日志中的 `security` 日志类型及内嵌 `SecurityEventEnvelope`。

## 部署边界

- 应用侧限流不能替代边界层 DDoS 防护，生产环境仍应在 Nginx/API Gateway/WAF 层做连接数、请求速率和 body size 限制。
- 项目不内置 WAF、完整审计平台或外部 KMS/HSM；本次交付的是项目内统一密钥管理基础设施和可扩展接入点。
- TLS 终止、可信代理头、真实客户端 IP 提取策略应由网关层统一声明；应用侧 production 默认不信任代理头，并在非可信来源下使用连接来源 IP。
- 生产环境应继续关闭公开 OpenAPI，并启用 HSTS/CSP。
- OpenTelemetry span event、依赖漏洞扫描和基础 DAST 流程属于后续治理项；当前文档仅保留接入边界说明，不声明已内置完整安全扫描平台。

## 测试结果

- 已在 Docker Compose 环境启动后执行 `.\.venv\Scripts\python.exe -m compileall src test -q`。
- `docker compose -f compose.yml up -d`：`app`、`postgres`、`redis`、`rabbitmq` 均已按依赖启动。
- 已执行完整回归 `$env:RABBITMQ_INTEGRATION_ENABLED='1'; .\.venv\Scripts\python.exe -m pytest -q`，结果为 `630 passed, 62 warnings`。
