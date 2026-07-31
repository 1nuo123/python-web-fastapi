# 响应信封

## 1. 这是什么

定义项目统一响应结构 `ResponseEnvelope`：字段语义、泛型用法、工厂构造方式、与 orjson 序列化的配合，以及正常响应与“响应尚未开始的可控错误”为何共享同一 body 结构。

**最后更新范围**：覆盖 `src/core/http_contract/response_envelope_contract.py`、`request_scope_contract.py` 与 `orjson_document_response.py`。

## 2. 结构定义

```json
{
  "header": {
    "code": "system.success.ok",
    "message": "健康探针正常。",
    "request_id": "0b8f4c2e-....",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
  },
  "data": { "kind": "health_probe", "schema_version": "1.0", "status": "ok", "ready": true }
}
```

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `header.code` | str | 稳定业务码：成功 `system.success.ok`，失败为错误码目录中的值。**判断成败看它，不只看 HTTP 状态码**（虽然二者当前始终一致）。 |
| `header.message` | str | 人类可读中文短句，允许直接展示。 |
| `header.request_id` | str | 请求唯一标识；正常回程和由内层具体异常处理器生成的响应通常同时由 `RequestScopeMiddleware` 写入同值 `X-Request-ID`。最外层 catch-all 500 不再经过该响应阶段，不能无条件保证响应头存在。 |
| `header.trace_id` | str \| null | 链路追踪 ID；OTel 关闭且客户端未传 `X-Trace-ID` 时为 null。 |
| `data` | 泛型 `T_ResponsePayload`（bound=BaseModel） | 业务载荷；失败时为 `HttpFaultPayload{kind:"http_fault", schema_version:"1.0", status_code, error_code}`。 |

`ResponseEnvelope[T]` 是 Pydantic 泛型模型，`extra="forbid"`；路由的 `response_model=ResponseEnvelope[XxxPayload]` 使 OpenAPI 精确到具体 payload 类型。

**适用边界**：该信封覆盖项目 RouteCatalog 的正常响应、`HttpFaultException`、请求模型 422，以及 PayloadGuard/Authentication/RateLimit 主动短路。它不覆盖框架/运维表面：CORS 预检可由最外层 `CORSMiddleware` 直接返回，未匹配路由与方法不允许仍走 FastAPI 默认 `HTTPException` handler，`/metrics` 是 Prometheus 文本格式，`/openapi.json`、`/docs`、`/redoc` 也使用框架原生响应。客户端不能假设任意 URL、任意状态码的 body 都是本信封。

## 3. 为什么这样设计

- **客户端解析收敛**：正常响应、路由业务异常、422，以及中间件主动短路的 413/401/429 都使用相同 body 结构，SDK 可共用解析与错误分派（按 `header.code` 前缀分域：`system.*`/`auth.*`/`admin.identity.*`）。协议层已开始响应后发生的异常不在此保证内。
- **payload 自带 kind/schema_version**：`data` 内部再带类型标识与版本，客户端可以在不看 URL 的情况下识别载荷类型，也为后续版本演进（1.0→1.1 加字段）提供判别依据。项目内 `TokenIssuePayload` 已经历 1.0→1.1（增加 `refresh_expires_in_seconds`）的演进。
- **request_id 贯穿**：中间件生成 → 信封回填 → 响应头回写 → 结构化日志携带，四点同源，形成排障闭环。

## 4. 构造方式

统一经 `ResponseEnvelopeFactory.build(code, message, request_scope, data)`——工厂从 `RequestScope` 摘取 request_id/trace_id 填 header。工厂本身无状态，`ApplicationContainer.response_factory` 与各异常出口各持有实例。

序列化由 `OrjsonDocumentResponse`（FastAPI 的 `default_response_class`）完成：正常路由返回模型时走该默认类；异常 presenter 与中间件短路路径显式执行 `envelope.model_dump(mode="json")` 并实例化同一响应类。两条路径因此使用同一 JSON renderer，但触发机制不同。

## 5. 怎么用

- 成功：`return context.response_factory.build(code=str(SuccessCode.OK), message="...", request_scope=context.request_scope, data=payload)`。
- 失败：抛 `HttpFaultException`，由异常处理器构造信封，路由不手工拼错误响应。
- 客户端侧建议：先看 HTTP 状态码粗分类，再按 `header.code` 精确分派；重试仅对 `system.request.timeout`/`system.capacity.exhausted`/429 且遵守 `Retry-After`。

## 6. 注意事项

- 不要在 payload 外再包一层自定义 wrapper，也不要给 header 加字段——header 结构变更影响全部接口与全部客户端，必须走契约评审。
- 对于 `ResponseEnvelope`，`data` 恒不为 null：无实义数据的项目接口也返回带 kind 的载荷模型；这条规则不适用于上述框架/运维原生响应。
- 统一信封是应用层可控响应契约，不是对 ASGI 传输失败的保证。流式响应已开始后发生异常时，服务端不能回滚已发送字节；客户端必须仍把无完整 JSON/连接中断作为传输错误处理。
- 修改信封相关代码时同步 `public_contract_snapshot_builder` 基线与 contract 测试。

## 7. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| contract | `test/contract_test/test_http_contract.py` | 信封字段、extra 禁止、泛型行为。 |
| interface | `test/interface_test/test_http_interface.py` | 正常/异常路径信封一致性与响应头。 |

## 8. 相关文档

- [项目文档总览](../README.md)
- [异常处理](exception_handling.md)
- [路由契约模式](route_contract_pattern.md)
