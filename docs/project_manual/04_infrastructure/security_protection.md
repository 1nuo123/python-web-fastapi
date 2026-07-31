# 安全防护

## 1. 这是什么

详解安全防护运行时（`security_protection_runtime`）的五类守卫——流控限流、IP 封禁、风险信号、Token-IP 绑定、出站 URL 安全——以及安全事件体系（构建、指标、审计级落库）与客户端 IP 可信解析。

**最后更新范围**：覆盖 `src/infrastructure/security/` 全部 10 个文件、`security_runtime_contract.py` 配置模型与 `SecurityEventBuilder` 事件目录。

## 2. 设计思想与动机

- **守卫全部以缓存为存储**：限流窗口、封禁缓存、风险计数、Token 绑定摘要都存 `CacheStore`（生产 Redis），多实例天然共享防护状态；封禁记录另落库（`security_ip_block_record` 表）保证可审计与重启恢复。
- **fail-closed**：限流缓存故障时按 `flow_control.fail_mode=fail_closed` 拒绝请求而不是放行——防护组件失效时收紧而非敞开。
- **事件先行**：每个拒绝/风险判定都产出结构化 `SecurityEventEnvelope`（类型/决策/严重级/脱敏字段），进日志管道与 Prometheus 指标；审计关键类型即时落库。
- **敏感值只存摘要**：IP、令牌、主机名经 `SensitiveDigestService`（以 jwt_secret 为盐的 HMAC 摘要）后入键/入事件，防护数据不落原文。

## 3. 组件详解

### 3.1 ClientIpResolver（可信 IP 解析）

`X-Forwarded-For` 只有在直连对端属于 `client_ip.trusted_proxy_cidr_blocks` 时才被信任（取最后一个不可信跳之前的地址）；否则用 socket 对端地址。默认信任环回（本地开发）；**生产配置校验禁止环回 CIDR**，必须显式声明真实代理网段——否则伪造 XFF 可绕过全部 IP 维度防护。

### 3.2 RateLimitGuard（滑动窗口限流）

按策略键（policy_name + 维度组合）在缓存中做窗口计数。键维度 `key_dimensions` 可组合 ip/path/认证头摘要；默认策略 `default_limit/default_window_seconds`（基线 120 次/60s），路径级策略在 `flow_control.policies`（`RateLimitPolicyEnvelope` 列表：path、method、limit、window、block_seconds、block_when_exceeded、key_dimensions）中声明。超限决策 `RETURN_429` 并可按 `block_when_exceeded` 触发临时 IP 封禁。

### 3.3 IpBlockGuard（IP 封禁）

双层存储：缓存（TTL=`cache_ttl_seconds`，热路径查询）+ 数据库记录（含来源、原因、过期时间）。手工封禁经 `/security/ip-blocks` API 或限流触发自动封禁（`default_block_seconds`，基线 900s）。检查在限流守卫组合链最前——被封 IP 直接 429。释放走 release 端点（软释放留痕）+ 缓存失效。分布式锁保护"查库-写缓存"回填竞态。

### 3.4 RiskSignalGuard（风险信号）

轻量启发式：密码喷洒疑似检测（`password_spray_limit` 次失败/`password_spray_window_seconds` 窗口，跨用户名维度计数），产出风险安全事件供告警与后续策略消费；当前不直接拒绝请求。

### 3.5 TokenBindingGuard 与 OutboundUrlSafety

Token-IP 绑定见[鉴权与授权](authentication_and_authorization.md)第 4 节；出站 URL 安全（SSRF 防护）见[出站 HTTP 安全](outbound_http_safety.md)。

### 3.6 SecurityProtectionGuard（组合守卫）

限流中间件的唯一入口：`evaluate_request` 按序执行 IP 封禁检查 → 限流评估 →（登录路径）风险信号记录，产出 `SecurityDecision{action, retry_after_seconds, security_event}`。组合对象持有全部子守卫与事件构建器，中间件不感知子守卫细节。

## 4. 安全事件体系

`SecurityEventEnvelope`（`security_event_contract.py`，237 行）：header 含 event_type/decision/severity/request 上下文摘要，detail 按事件类型强类型化。主要类型：限流拒绝、IP 封禁命中/创建/释放、载荷超限、token_binding 不匹配、authorization_denied、密码喷洒疑似、出站 URL 拒绝、`ADMIN_IDENTITY_CHANGED`（后台身份变更审计）、`CONFIG_SECURITY_REJECTED`（配置热更新被拒）。

流向：`emit_security_event` → 包装为 `SecurityLogDetail` 日志事件（AUDIT_CRITICAL 类型同步落库，其余走缓冲）→ `fastapi_security_event_total{event_type,decision,severity}` 指标（标签全部来自封闭枚举，无基数风险）→ `/admin/security-events` 可查。

## 5. 配置总览（runtime.security）

信封结构：`header{mode: development_security|production_security, enabled, policy_name}` + `detail{expose_openapi, expose_system_info, require_external_jwt_secret, require_distributed_auth_throttle, enable_hsts, enable_csp, protection{...}}`。`protection` 五块：

| 块 | 关键字段（默认） |
| --- | --- |
| `flow_control` | enabled(true)、default_limit(120)、default_window_seconds(60)、fail_mode(fail_closed)、policies[] |
| `risk_control` | enabled(true)、password_spray_limit(10)、password_spray_window_seconds(300) |
| `client_ip` | trusted_proxy_cidr_blocks（默认环回；生产必须改） |
| `ip_block` | enabled(true)、cache_ttl_seconds(60)、default_block_seconds(900) |
| `token_binding` | enabled(false)、mode(high_risk_only)、ip_digest_ttl_seconds(900)、applicable_paths、token_uses |
| `outbound_url_safety` | enabled(true)、allowed_schemes(http/https)、deny_private_networks、deny_metadata_address、deny_cidr_blocks、deny_hostnames（生产另须 host allowlist） |

生产模式（`production_security`）下 SettingsSecurityValidator 强制收紧项见[配置系统](configuration_system.md)第 4 节。

## 6. 怎么用

- 给高频接口定制限流：在 `security_runtime_{env}.toml` 的 `protection.flow_control.policies` 增加策略信封（path/method/limit/window/block_seconds/key_dimensions）。
- 紧急封禁：`POST /security/ip-blocks`（需 `security:manage`）；解除 `POST /security/ip-blocks/release`。
- 接入真实代理拓扑：把 LB/网关网段写进 `trusted_proxy_cidr_blocks`，并验证 `/admin/security-events` 中记录的 client_ip 摘要维度正确。

## 7. 注意事项

- 限流键中的认证头参与摘要意味着同一 IP 上不同用户各自计窗；匿名请求退化为 IP 维度。
- fail_closed 在 Redis 故障时会造成全量 429——这是设计选择；Redis 高可用是生产前置条件，相关告警见 alert 基线。
- 封禁缓存 TTL 与库记录过期是两个时钟：缓存过期后首次命中会回源查库回填，短暂窗口内已过期封禁可能多拦一次查询（无正确性问题）。
- 新增安全事件类型：契约枚举 + builder 方法 + （如需）AUDIT_CRITICAL 白名单 + 指标标签自动生效 + 告警规则评估，五处检查。

## 8. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_security_guard_unit.py` 等 | 各守卫决策逻辑。 |
| unit | `test/unit_test/test_client_ip_resolver_unit.py` | 可信代理解析。 |
| interface | `test/interface_test/test_rate_limit_http_interface.py` | 限流/封禁 HTTP 行为。 |
| interface | `test/interface_test/test_security_event_interface.py` | 事件产出与查询。 |
| exception | `test/exception_test/test_security_exception.py` | fail_closed 与故障注入。 |

## 9. 相关文档

- [项目文档总览](../README.md)
- [安全防护 API](../05_api_reference/security_protection_api.md)
- [出站 HTTP 安全](outbound_http_safety.md)
- [鉴权与授权](authentication_and_authorization.md)
- [security_protection_runtime 说明](../../security_protection_runtime说明.md)
