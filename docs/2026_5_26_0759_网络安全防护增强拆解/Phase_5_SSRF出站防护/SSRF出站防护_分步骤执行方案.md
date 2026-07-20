# SSRF 出站防护分步骤执行方案

## 阶段目标

补齐 outbound HTTP SSRF 轻量防护，在出站请求发起前拒绝本机、内网、link-local、metadata 地址。

## 全局约束

- 若文档、图谱、源码冲突，以当前源码为准，历史文档可能过期。
- 必须遵守 `docs/standard/编码规范.md`、`docs/standard/测试规范.md`、`docs/standard/命名规范.md`。
- 本次不引入完整 SIEM、WAF、规则引擎或审计平台；安全事件复用现有结构化日志/事件链路扩展。
- `runtime.security` 只承载安全防护策略；`runtime.distributed_lock` 和 `runtime.key_management` 是独立运行时配置入口。
- 缓存 key 必须符合 `key_prefix:namespace:segment...`，令牌、密码、密钥、IP、User-Agent 参与 key 构造前必须摘要化。
- 新增契约统一采用“公共头字段 + 强类型扩展字段”。
- 扩展字段必须使用 Pydantic 判别联合，包含 `kind`、`schema_version`，并启用 `extra="forbid"`。
- 禁止用 `dict[str, Any]`、`metadata`、`extra_payload` 承载稳定协议。
- 外层类型与内层扩展类型必须一致。
- 不记录明文密码、Bearer、JWT、refresh token、secret、完整请求体、完整 URL 查询串。
- IP、User-Agent、token、host 相关标识默认只保存摘要。
- 日志、异常、注释使用中文；不得使用 `print`。
- 测试必须覆盖资源释放，不能通过跳过测试、放宽断言或回退实现规避失败。

## 阶段依赖

- Phase 1 的 `OutboundUrlSafetyEnvelope`。
- Phase 2 的 `SensitiveDigestService`。
- 当前 outbound HTTP client 契约和运行时装配。
- 阶段关系：Phase 5 依赖 Phase 1、Phase 2，补齐 outbound HTTP SSRF 轻量防护。

## 相关文件

```text
config/
  runtime/
    security_runtime/
      security_runtime_base.toml                    # 修改：补充 flow/risk/ip_block/token_binding/outbound_url 配置
      security_runtime_production.toml              # 修改：生产安全覆盖
      security_runtime_test.toml                    # 修改：测试安全覆盖

src/
  core/
    security_contract/
      outbound_url_safety_contract.py               # 新增：出站 URL 安全契约
      security_event_contract.py                    # 新增：安全事件契约
  infrastructure/
    key_management/
      sensitive_digest_service.py                   # 新增：敏感标识摘要服务
    security/
      outbound_url_safety_validator.py              # 新增：SSRF URL 校验器
      security_event_builder.py                     # 新增：安全事件构建器
    outbound_http_client.py                         # 修改或保留：接入 URL 安全校验

test/
  unit_test/
    test_outbound_url_safety_validator_unit.py      # 新增：SSRF 校验单元测试
```

## 原始模拟用法

```python
validator.validate_url("http://169.254.169.254/latest/meta-data")
```

## 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| OutboundUrlSafetyEnvelope | 出站 URL 安全信封 | Phase 1 契约，定义允许 scheme、禁止地址段、metadata IP 阻断策略 |
| OutboundUrlSafetyValidator | 出站 URL 安全校验器 | 校验 scheme、host、端口、解析地址和禁止网段 |
| OutboundUrlSafetyDecision | 出站 URL 安全决策 | 输出 allow/deny、原因码和事件类型 |
| SsrfSecurityEventDetail | SSRF 安全事件扩展 | 记录被拒绝的出站 URL 安全事件，只保存 host 摘要 |
| SensitiveDigestService | 敏感标识摘要服务 | Phase 2 依赖，用于 host 等敏感标识摘要化，避免记录明文敏感信息 |

## 分步骤执行

### 步骤一：确认配置与契约

- 基于 Phase 1 的 `OutboundUrlSafetyEnvelope` 接入 `runtime.security` 下的 outbound URL 安全策略。
- 保持契约“公共头字段 + 强类型扩展字段”结构，扩展字段包含 `kind`、`schema_version`，并启用 `extra="forbid"`。
- 禁止使用 `dict[str, Any]`、`metadata`、`extra_payload` 承载稳定 SSRF 协议。

### 步骤二：新增出站 URL 安全校验器

- 新增 `OutboundUrlSafetyValidator`。
- 禁止空 host、非法端口、非 `http/https` scheme。
- 禁止 `localhost`、loopback、private、link-local、metadata IP。
- URL 解析和 IP 分类规则必须覆盖 IPv4、IPv6、本机、私网、link-local 和 metadata 地址。

### 步骤三：接入 outbound HTTP client

- 在 outbound HTTP client 发起请求前调用 `validator.validate_url(...)`。
- 被拒绝时返回 `OutboundUrlSafetyDecision` 的 deny 结果，包含原因码和事件类型。
- 合法公网 `https` URL 允许继续发起请求。

### 步骤四：生成 SSRF 安全事件

- 被拒绝时生成 `ssrf.blocked` 安全事件。
- 使用 `SensitiveDigestService` 对 host 相关标识摘要化。
- 安全事件只保存 host 摘要，不记录完整 URL 查询串。
- 日志、安全事件、指标中不出现明文敏感信息。

### 步骤五：测试与回归

- 新增 SSRF URL 校验测试，覆盖本机、私网、link-local、metadata、公网 URL。
- 回跑 `test/unit_test/test_outbound_url_safety_validator_unit.py`。
- 回跑真实测试清单中包含 SSRF 的单元测试批次。
- 若 SSRF 校验误拦截或漏拦截，修正 URL 解析和 IP 分类规则，并回跑失败用例所在测试文件。

## 校验与验收点

- `localhost`、`127.0.0.1`、`::1` 被拒绝。
- `10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16` 被拒绝。
- `169.254.169.254` 被拒绝。
- 合法公网 `https` URL 可通过。
- outbound URL 指向本机、内网或 metadata IP 时被拒绝。
- 认证失败、refresh token 复用、限流拦截、请求体过大、SSRF 拦截、Token-IP 异常能生成统一安全事件。
- 现有认证、日志、健康检查、metrics、OpenTelemetry 接入点行为不回退。
- 日志、安全事件、指标中不出现明文敏感信息。
- 所有测试通过。
- 限流、封禁、独立分布式锁、统一密钥管理、密钥轮转、Token-IP 绑定、SSRF、payload、认证风险路径符合验收标准。
- 测试结束后释放数据库 session、缓存连接、HTTP client、锁租约和 TestClient。

## 真实测试

```bash
docker compose up -d
uv run python -m compileall -q src test
uv run python -m pytest -q test/unit_test/test_outbound_url_safety_validator_unit.py
uv run python -m pytest -q test/unit_test/test_distributed_lock_provider_unit.py test/unit_test/test_key_management_service_unit.py test/unit_test/test_key_rotation_service_unit.py test/unit_test/test_rate_limit_guard_unit.py test/unit_test/test_ip_block_guard_unit.py test/unit_test/test_security_event_builder_unit.py test/unit_test/test_token_binding_guard_unit.py test/unit_test/test_outbound_url_safety_validator_unit.py
uv run python -m pytest -q
```

## 审查同步记录（2026-05-26）

- SSRF 配置、契约、URL 校验器、同步/异步 httpx hook、启动主流程 hook 安装和单测已落地；全量回归为 392 passed、71 warnings。
- `SharedResourceMount` 启动装配测试已覆盖同步与异步 hook，`apply_settings()` 热切换后会重建 validator 并重新安装 hook。
- DNS 重绑定/TOCTOU 当前仍是请求前解析校验，未实现连接解析绑定或 DNS pinning；已在任务清单记录为残余风险边界。
