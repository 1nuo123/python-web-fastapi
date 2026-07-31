# 异常处理

## 1. 这是什么

说明项目的异常模型（`HttpFaultException` + 稳定错误码目录）与三个异常处理器的行为，包括它们分别位于 Starlette 异常栈的哪一层、每种异常路径对客户端暴露什么、对日志记录什么、脱敏边界在哪。

**最后更新范围**：覆盖 `src/core/exception_contract/`、`src/infrastructure/fastapi_exception_presenter.py` 与中间件内的短路故障响应。

## 2. 设计思想与动机

- **单一业务异常类型**：全项目业务失败只抛 `HttpFaultException(status_code, error_code, message, detail=None)`。不派生子类的原因：异常的差异全部由 `error_code`（稳定字符串枚举）表达，处理器只需要一个 catch 分支；错误码目录即对外契约。
- **message 对外、detail 对内**：`message` 是可安全展示给客户端的中文短句；`detail` 是诊断信息（如底层异常串），只进结构化日志，序列化 payload（`to_payload()`）只含 `status_code + error_code`，不含 detail。
- **未预期异常绝不外泄**：任何未捕获异常统一转 500 `system.internal.unexpected`，客户端只看到"服务内部异常"；traceback 进脱敏后的结构化日志（`SensitiveTextRedactor` 处理）。
- **可控异常路径与正常路径同构**：在响应尚未开始时，异常响应也是 `ResponseEnvelope`，带 request_id/trace_id，客户端解析逻辑唯一；如果 `http.response.start` 已发送，ASGI 层无法再替换 body，这一协议限制必须单独处理。

## 3. 错误码目录

| 枚举 | 前缀 | 内容 |
| --- | --- | --- |
| `SuccessCode` | `system.success.` | `OK = system.success.ok` |
| `CoreErrorCode` | `system.` | `request.invalid`(422)、`request.payload_too_large`(413)、`request.timeout`(504)、`capacity.exhausted`(503)、`config.invalid`、`internal.unexpected`(500)、`resource.not_ready`(503)、`reload.rejected`、`reload.failed`、`task.failed`、`database.unavailable`、`cache.unavailable` |
| `AuthErrorCode`（domain） | `auth.` | `access.invalid_credentials`、`access.account_disabled`、`token.invalid/expired/revoked/reused`、`authorization.permission_denied`、`request.throttled` |
| `AdminIdentityErrorCode`（domain） | `admin.identity.` | 身份管理域业务错误 |

错误码是稳定契约：只增不改不删；HTTP 状态码由抛出点按语义选择（同一错误码可在不同场景配不同状态码，如 `token.invalid` 恒为 401）。

## 4. 三个全局处理器（FastApiExceptionPresenter）

`bind(app)` 依次向 `app.exception_handlers` 注册下列映射。构建 ASGI 栈时，FastAPI/Starlette 会把 `Exception`（或 500）映射拿出来交给最外层 `ServerErrorMiddleware`；另外两个具体异常映射交给用户中间件内侧的 `ExceptionMiddleware`。所以三者虽由同一个 presenter 注册，实际捕获边界并不相同：

| 处理器 | 捕获 | 响应 | 日志 |
| --- | --- | --- | --- |
| `handle_http_fault` | `HttpFaultException` | `exc.status_code` + `header.code=exc.error_code` + `data=HttpFaultPayload` | `build_exception_event(include_traceback=False)` 投缓冲 + 一行 warning |
| `handle_request_validation` | `RequestValidationError` | 422 `system.request.invalid`，message="请求参数校验失败。" | 同上（不含 Pydantic 细节，防止字段值回显泄漏） |
| `handle_unexpected_exception` | 逃出整个用户中间件/路由栈的 `Exception` | 500 `system.internal.unexpected` | 由最外层 `ServerErrorMiddleware` 调用；`include_traceback=True` 的脱敏结构化日志 + 一行 error；响应发送后框架仍重新抛出供服务器记录 |

request_scope 缺失时（异常发生在 RequestScope 建立前，或 handler 被独立调用）用 `request_id="request-scope-missing"` 的合成作用域兜底，保证信封结构完整。

注意 422 响应**不返回**字段级校验错误明细——这是有意决策：校验细节可能包含请求原文（密码、令牌片段）。需要调试时看服务端结构化日志。

`FastApiExceptionPresenter` 没有覆盖 Starlette/FastAPI 的 `HTTPException` 映射，因此未匹配路由 404、方法不允许 405 等继续使用框架默认 body（通常含 `detail`），不是 `HttpFaultPayload` 信封。若产品契约要求这些状态也统一，必须新增并测试显式 handler，不能仅修改本文。

## 5. 中间件内的短路故障与框架边界

用户中间件位于 `ExceptionMiddleware` 外侧；其中抛出的 `HttpFaultException` 不会命中 `handle_http_fault`，而会逃到 `ServerErrorMiddleware` 并被 catch-all 当作未预期 500。为保留预期状态码，以下路径自行构造统一信封：

- PayloadGuard：413 `system.request.payload_too_large` + 安全事件。
- AuthenticationBinding：401 `auth.token.*` / 403 `auth.access.account_disabled` + 结构化异常日志。
- RateLimit：429 `system.request.invalid`（message"请求过于频繁。"）+ `Retry-After`；守卫抛出的 `HttpFaultException`（如缓存故障 fail_closed）原样转信封。

它们与处理器产出的信封字段完全一致，客户端无感差异。

短路位置会影响响应头与后处理：413/401/429 只沿已经进入的外层中间件回程，不会经过尚未进入的 SecurityHeader、ElapsedProbe、AccessLog。路由内 `HttpFaultException` 和 422 在最内侧被处理，会正常穿过用户中间件的响应阶段。catch-all 500 则由最外层直接发送，不会再穿过用户中间件响应阶段；信封 body 有 request_id，不等于一定存在 `X-Request-ID`/安全头/耗时头。

若下游已经发送 `http.response.start`，`ServerErrorMiddleware` 仍调用 catch-all 记录异常，但不会再发送新的 500 信封，并会继续重抛。此时客户端可能得到部分响应或连接错误，不能声称“任何失败都必然返回统一 JSON”。

## 6. 怎么用

- 用例中业务失败：`raise HttpFaultException(status_code=HTTPStatus.CONFLICT, error_code=AdminIdentityErrorCode.XXX, message="...", detail=诊断串)`。选状态码 → 选/增错误码（枚举）→ message 写用户可读中文 → detail 放内部诊断。
- 不要捕获后吞掉未预期异常再返回自造错误——让它冒泡到 `handle_unexpected_exception`，保证 traceback 进日志。
- 事务用例的异常纪律：`except HttpFaultException: rollback; raise`、`except Exception: rollback; raise`、`finally: dispose`（参照 `IssueAccessTokenUsecase.execute`）。

## 7. 注意事项

- `handle_http_fault` 的日志事件 `include_traceback=False`：业务异常不记栈（量大且无诊断价值）；需要栈的场景说明它不该是业务异常。
- 异常日志经 `LogEventBuilder.build_exception_event` 构建，client_ip/user_agent 取自请求上下文，detail/traceback 会被 `SensitiveTextRedactor` 脱敏（令牌、密码模式）后入库。
- `handle_request_validation` 不把 `exc.errors()` 或请求原文写入异常 detail；它记录的是固定内部说明“请求参数校验未通过。”。这减少泄漏，但也意味着字段级定位应依靠可控复现与接口 contract，而不是期待该异常事件保存完整 Pydantic 明细。
- 新增错误码时同步：枚举 → 抛出点 → 相关 API 文档错误码表 → interface 测试断言。

## 8. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| exception | `test/exception_test/*` | 三处理器行为、脱敏、故障注入。 |
| interface | `test/interface_test/test_http_interface.py` | 422/500 信封结构。 |
| contract | `test/contract_test/test_http_contract.py` | `HttpFaultPayload` 契约。 |

## 9. 相关文档

- [项目文档总览](../README.md)
- [响应信封](response_envelope.md)
- [请求生命周期](../01_architecture/request_lifecycle.md)
- [日志运行时](../04_infrastructure/logging_runtime.md)
