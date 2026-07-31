# 中间件链

## 1. 这是什么

逐个拆解 7 个项目中间件、可选 CORS 与可选 Prometheus 指标中间件的实现细节：各自读写了 `request.state` 的哪些字段、在什么条件下短路返回、顺序为什么不能变。[请求生命周期](../01_architecture/request_lifecycle.md)给出链路全景，本文给实现级细节。

**最后更新范围**：覆盖 `src/infrastructure/middleware_chain/` 全部 7 个文件、`fastapi_middleware_plan.py` 与 `prometheus_metrics_route.py` 的中间件部分。

## 2. 顺序声明与绑定方式

`FastApiMiddlewarePlan.build_bindings` 返回**按请求进入顺序**的 `Middleware` 列表；装配器执行 `app.user_middleware = [*bindings, *app.user_middleware]` 一次性前插。为什么不逐个 `add_middleware`？因为 `add_middleware` 会插入 `user_middleware[0]`，即“后加的在外层”；直接拼列表让计划内部“列表顺序 = 执行顺序”成为不变量，路径测试可直接断言。

条件项：CORS 启用时插到计划最前（索引 0）；AccessLog 启用时追加最后；Prometheus HTTP 指标由装配器在计划绑定后另行 `add_middleware`，因而位于所有用户中间件最外层。OTel 关闭时，Starlette 把带项目 catch-all 的 `ServerErrorMiddleware` 放在全部用户中间件之外、把具体异常映射所在的 `ExceptionMiddleware` 放在用户中间件之内。OTel 开启时，当前 instrumentation 重写栈构建，在这些层之外/之间增加默认 server-error 兜底、`OpenTelemetryMiddleware` 和异常记录包装；它们不属于计划列表，也不写 `middleware_trace`。

## 3. 各中间件实现细节

### 3.1 RequestScopeMiddleware（BaseHTTPMiddleware）

- 读 `X-Request-ID` 头，缺失则 `uuid4()`；trace id 经 `FastApiOtelBridge.read_trace_id`（OTel 启用优先解析 `traceparent` 第二段，否则回落 `X-Trace-ID` 头）。
- 构建 `RequestScope{request_id, trace_id, request_time_epoch, request_path, request_method}` 写入 `request.state.request_scope`，并 `RequestContextManagerImpl.set_current_scope` 绑定到 contextvar——出站 HTTP 安全钩子与日志构建器由此在无 Request 对象的上下文取到当前请求信息。
- 初始化 `request.state.middleware_trace = ["request_scope"]`。
- finally 中 `clear_current_scope()`，避免 contextvar 泄漏到复用的事件循环任务。

### 3.2 PayloadGuardMiddleware（纯 ASGI）

唯一的纯 ASGI 实现，因为它必须替换 `receive` 通道：

- 快路径：可解析的 `content-length` 头 > `runtime.web.max_request_body_bytes` → 直接构造 413 信封返回（不读 body），同时经 `SecurityEventBuilder.build_payload_event` 发安全事件；非法长度按“未知”处理，继续由流式累计兜底。
- 慢路径兜底：包装 `PayloadLimitedReceive` 流式累计 `http.request` 消息字节数，超限抛 `RequestPayloadTooLargeSignal`；`ResponseStartTracker` 记录下游是否已发 `http.response.start`。若尚未开始响应则原地转 413；若已经开始，只能上抛到 server-error 层做日志处理，不能再发送统一 413 body，且 Starlette 会继续向服务器重抛。
- 413 响应也复用统一信封（`system.request.payload_too_large`）。

### 3.3 AuthenticationBindingMiddleware（BaseHTTPMiddleware）

- 初始化 `request.state.authenticated_principal = None`、`request.state.auth_fault = None`。
- `OAuth2SchemeProvider.extract_bearer_token`：无 Bearer → 直接放行（是否强制认证由路由守卫决定）。
- 有 Bearer：`JwtTokenService.decode_token(expected_use=ACCESS)` →（经 `run_sync` 线程池）`_bind_authenticated_principal` 逐项校验：主体存在/启用、令牌会话存在、会话主体一致、会话未不一致/未吊销/未过期。全部通过后 `AuthenticatedPrincipal.from_authorization_snapshot` 绑定，并把 subject_id 回填进 contextvar 与 `request.state.request_scope`，供日志/安全事件读取；统一响应 header 本身没有 subject_id 字段。
- 可选 Token-IP 绑定：`runtime.security.detail.protection.token_binding` 启用且路径/token_use 命中时，`TokenBindingGuard.validate_or_bind`（首次绑定 IP 摘要，后续比对）；不匹配 → 发 `token_binding.mismatch` 安全事件 + 401。
- 任何 `HttpFaultException` → 记录结构化异常日志 + 短路返回统一信封；故障对象同时存入 `request.state.auth_fault`。按当前 dispatch 路径短路后路由守卫不会执行，accessor 对 `auth_fault` 的优先重抛属于防御性一致语义。
- 查库使用独立 UnitOfWork 且 finally `dispose()`——中间件只读查询也显式还连接，防止泄漏到长请求。

### 3.4 RateLimitMiddleware（BaseHTTPMiddleware）

- `RateLimitMiddleware` 始终在计划中并先追加 `rate_limit` trace；flow_control 与 ip_block 都关闭时才跳过防护逻辑并直通。
- `_resolve_policy`：遍历 `flow_control.policies`（`RateLimitPolicyEnvelope` 列表），按 enabled + path 精确匹配 + method（空=任意，`*`=任意）取第一条命中；无命中用默认 limit/window/block。
- 委托 `SecurityProtectionGuard.evaluate_request`（组合 IP 封禁检查、滑动窗口限流、密码喷洒风险信号），入参含认证头值（Authorization/X-API-Key 参与限流键，做用户维度限流）。
- 决策 `RETURN_429` → 发安全事件 + 429 信封 + `Retry-After` 头；缓存故障的行为由 `flow_control.fail_mode` 决定，`fail_closed` 时守卫抛故障并由中间件转信封，不能把该行为写成所有配置固定拒绝。

### 3.5 SecurityHeaderMiddleware / ElapsedProbeMiddleware / AccessLogMiddleware

- SecurityHeader：响应后按 `runtime.web.enable_security_headers` 追加 nosniff/DENY/no-referrer/Permissions-Policy 四常规头，按 `security.detail.enable_hsts/enable_csp` 追加 HSTS（31536000s 含子域）与 CSP（`default-src 'none'`）；`include_middleware_trace_header=true` 时输出 `X-Middleware-Trace`。
- ElapsedProbe：入站开始 perf_counter，`await call_next` 返回后才写 `request.state.elapsed_milliseconds` 与 `X-Elapsed-Ms`（两位小数）。
- AccessLog：内层返回后从 `request.scope["route"]` 取 route_name，读取 `request.state.elapsed_milliseconds`（缺失用 `0.0`），构建 access 日志事件并另打一行 info。当前它在 ElapsedProbe 内层，所以 AccessLog 的回程逻辑先执行，实际结构化访问日志耗时为默认 `0.0`；`X-Elapsed-Ms` 和外层 Prometheus 仍各自正常计时。

### 3.6 PrometheusHttpMetricsMiddleware

最外层可选；用路由模板（`request.scope["route"].path`）做 path 标签，未匹配路由记 `unmatched`；注册器再做一层动态段防御（纯数字/长十六进制段归入 `unknown`），双保险控制标签基数。

## 4. 为什么是这个顺序

| 约束 | 原因 |
| --- | --- |
| RequestScope 最先（除 CORS） | 后续所有中间件与异常出口都要读 request_scope/middleware_trace；CORS 预检响应不需要业务上下文所以可以更外。 |
| PayloadGuard 在认证前 | 超大包体应在做任何昂贵操作（JWT 解码、查库）前被拒。 |
| AuthenticationBinding 在 RateLimit 前 | 限流键可用认证信息做用户维度限流；同时无效令牌被更早拒绝，不消耗限流窗口。 |
| SecurityHeader 在内层 | 它在响应阶段工作，包在内层能覆盖路由与更内层产生的响应；中间件链内短路响应（413/401/429）由各自构造处自行保证信封一致。 |
| ElapsedProbe / AccessLog 当前相邻 | 当前入站是 ElapsedProbe→AccessLog，回程反向，AccessLog 因而读不到尚未写入的 elapsed 值。这是现状而非目标；若要求访问日志记录真实耗时，应将 AccessLog 调整到 ElapsedProbe 外层或让其独立计时。 |

短路响应只经过已经进入的外层回程：PayloadGuard 413 不会拿到 SecurityHeader/Elapsed/AccessLog 的输出；Authentication 401 和 RateLimit 429 也不会经过它们的内层后处理。正常路由响应以及由内层 `ExceptionMiddleware` 处理的 `HttpFaultException`/422 会沿完整已进入链路返回。

## 5. 怎么用：新增中间件

1. 放 `src/infrastructure/middleware_chain/`；能用 `BaseHTTPMiddleware` 就用（简单），要操作 body 流/替换 receive-send 才写纯 ASGI。
2. 依赖资源一律收 `resource_mount` 构造参数，运行时经 `read_runtime_bundle()` 取配置（支持热更新）。
3. 在 `FastApiMiddlewarePlan.build_bindings` 选择插入位置，并把顺序理由写进本文件第 4 节。
4. 向 `request.state.middleware_trace` append 自己的名字。
5. 补 unit（顺序断言）+ interface（行为）测试。

## 6. 注意事项

- Starlette 把具体异常处理映射所在的 `ExceptionMiddleware` 放在用户中间件内侧。因此用户中间件抛出的 `HttpFaultException` 不会命中对应的具体 handler，而会逃到最外层 `ServerErrorMiddleware`，被 `Exception` catch-all 视为未预期 500；认证/限流中间件必须在本层把预期 `HttpFaultException` 转为统一信封。真正未预期异常仍由 catch-all 记录并构造 500，随后框架继续重抛供服务器记录。
- 中间件读配置必须每请求经 `read_runtime_bundle()` 读取，不要在 `__init__` 缓存 settings 字段值，否则热更新失效。
- `middleware_trace` 顺序被测试锁定；调整顺序要同步更新断言与本文。

## 7. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| path | `test/path_test/test_runtime_path.py` | `FastApiMiddlewarePlan` 顺序、资源门面注入与 AccessLog 条件分支。 |
| interface | `test/interface_test/test_http_interface.py` | trace 头、安全头、请求 ID 回写。 |
| interface | `test/interface_test/test_rate_limit_http_interface.py` | 429/Retry-After/fail_closed。 |
| interface | `test/interface_test/test_security_http_interface.py` | 安全响应头与公共路由无效 Bearer 的 401。 |
| interface | `test/interface_test/test_security_event_http_interface.py` | Token-IP、限流和 payload 413 的安全事件。 |

## 8. 相关文档

- [项目文档总览](../README.md)
- [请求生命周期](../01_architecture/request_lifecycle.md)
- [安全防护](../04_infrastructure/security_protection.md)
- [鉴权与授权](../04_infrastructure/authentication_and_authorization.md)
