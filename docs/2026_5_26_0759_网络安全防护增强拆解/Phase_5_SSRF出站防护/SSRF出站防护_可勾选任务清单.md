# SSRF 出站防护可勾选任务清单

## 步骤一：确认依赖与边界

- [x] 确认 Phase 1 的 `OutboundUrlSafetyEnvelope` 已冻结。
- [x] 确认 Phase 2 的 `SensitiveDigestService` 可用于 host 摘要化。
- [x] 确认当前 outbound HTTP client 契约和运行时装配位置。
- [x] 确认 `runtime.security` 只承载安全防护策略。
- [x] 确认不记录完整 URL 查询串，host 相关标识只保存摘要。

## 步骤二：补齐配置与契约

- [x] 检查 `security_runtime_base.toml` 的 outbound_url 配置。
- [x] 检查 `security_runtime_production.toml` 的生产安全覆盖。
- [x] 检查 `security_runtime_test.toml` 的测试安全覆盖。
- [x] 检查 `outbound_url_safety_contract.py` 是否符合“公共头字段 + 强类型扩展字段”。
- [x] 检查扩展字段包含 `kind`、`schema_version`，并启用 `extra="forbid"`。
- [x] 检查外层类型与内层扩展类型一致。
- [x] 检查未使用 `dict[str, Any]`、`metadata`、`extra_payload` 承载稳定协议。

## 步骤三：实现出站 URL 安全校验器

- [x] 新增 `OutboundUrlSafetyValidator`。
- [x] 禁止空 host。
- [x] 禁止非法端口。
- [x] 禁止非 `http/https` scheme。
- [x] 禁止 `localhost`。
- [x] 禁止 loopback 地址。
- [x] 禁止 private 地址。
- [x] 禁止 link-local 地址。
- [x] 禁止 metadata IP。
- [x] 覆盖 IPv4 URL 解析与分类。
- [x] 覆盖 IPv6 URL 解析与分类。
- [x] 输出 `OutboundUrlSafetyDecision`，包含 allow/deny、原因码和事件类型。

## 步骤四：接入 outbound HTTP client

- [x] 在 outbound HTTP client 发起请求前调用 `validator.validate_url(...)`。
- [x] 保留原始模拟用法语义：`validator.validate_url("http://169.254.169.254/latest/meta-data")`。
- [x] URL 被拒绝时阻断出站请求。
- [x] 合法公网 `https` URL 允许通过。

## 步骤五：生成 SSRF 安全事件

- [x] 被拒绝时生成 `ssrf.blocked` 安全事件。
- [x] 使用 `SensitiveDigestService` 摘要化 host。
- [x] `SsrfSecurityEventDetail` 只保存 host 摘要。
- [x] 日志、安全事件、指标中不出现明文敏感信息。
- [x] 不记录明文密码、Bearer、JWT、refresh token、secret、完整请求体、完整 URL 查询串。

## 步骤六：新增与回跑测试

- [x] 新增 `test_outbound_url_safety_validator_unit.py`。
- [x] 测试 `localhost` 被拒绝。
- [x] 测试 `127.0.0.1` 被拒绝。
- [x] 测试 `::1` 被拒绝。
- [x] 测试 `10.0.0.0/8` 被拒绝。
- [x] 测试 `172.16.0.0/12` 被拒绝。
- [x] 测试 `192.168.0.0/16` 被拒绝。
- [x] 测试 `169.254.169.254` 被拒绝。
- [x] 测试合法公网 `https` URL 可通过。
- [x] 回跑 `uv run python -m compileall -q src test`。
- [x] 回跑 `uv run python -m pytest -q test/unit_test/test_outbound_url_safety_validator_unit.py`。
- [x] 回跑 `uv run python -m pytest -q test/unit_test/test_distributed_lock_provider_unit.py test/unit_test/test_key_management_service_unit.py test/unit_test/test_key_rotation_service_unit.py test/unit_test/test_rate_limit_guard_unit.py test/unit_test/test_ip_block_guard_unit.py test/unit_test/test_security_event_builder_unit.py test/unit_test/test_token_binding_guard_unit.py test/unit_test/test_outbound_url_safety_validator_unit.py`。
- [x] 回跑 `uv run python -m pytest -q`。

## 步骤七：回归修复与验收

- [x] 若 SSRF 校验误拦截或漏拦截，修正 URL 解析和 IP 分类规则。
- [x] 修复后回跑失败用例所在测试文件。
- [x] 确认 outbound URL 指向本机、内网或 metadata IP 时被拒绝。
- [x] 确认 SSRF 拦截能生成统一安全事件。
- [x] 确认现有认证、日志、健康检查、metrics、OpenTelemetry 接入点行为不回退。
- [x] 确认测试结束后释放数据库 session、缓存连接、HTTP client、锁租约和 TestClient。
- [x] 确认所有测试通过。

## 步骤八：审查补充项

- [x] 新增 DNS 解析到环回、私网、link-local、metadata 的测试，优先 mock `socket.getaddrinfo`。
- [x] 新增 DNS 重绑定/TOCTOU 风险处置任务，明确校验解析结果与实际连接解析的边界。
- [x] 新增异步 `AsyncOutboundUrlSafetyHook` 阻断与事件测试。
- [x] 新增主流程装配测试，验证 `SharedResourceMount` 启动后同步/异步共享 HTTP client 均安装 SSRF hook。
- [x] 补充 `OutboundUrlSafetyDecision.event_type`，或修正任务口径，避免声称 decision 包含事件类型。
- [x] 补充原方案真实测试批次：contract、path、exception、boundary、interface、integration、initialization、security、http、metrics、redactor。
- [x] 补充 `apply_settings()` 热切换后重新安装 SSRF hook 的实现与测试。
- [x] 补充异步 HTTP 主流程装配的正式测试。
- [x] 补充 DNS 重绑定/TOCTOU 的残余风险边界说明；当前未实现连接解析绑定。

