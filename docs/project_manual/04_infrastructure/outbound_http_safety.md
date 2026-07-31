# 出站 HTTP 安全

## 1. 这是什么

详解对外发起 HTTP 请求的完整安全体系：共享 httpx 客户端（同步/可选异步）的装配与配置、SSRF 防护（URL 级校验 + 连接级 DNS pinning）以及出站安全事件。任何"服务端要请求外部 URL"的代码都必须走这里描述的通道。

**最后更新范围**：覆盖 `outbound_http_client_contract.py`、`resource_slot/shared_http_*`、`security/outbound_url_safety_*` 三个防护文件与 httpx 钩子/传输层安装点。

## 2. 设计思想与动机

- **共享客户端而非临时创建**：httpx 客户端持有连接池，随处 `httpx.get()` 会导致连接不复用、超时不统一、无法安装安全钩子。项目在资源启动时构建一个 `SharedHttpClient`（同步必有）与可选 `SharedAsyncHttpClient`，全局复用。
- **SSRF 双层防御**：
  - **URL 级**（`validate_url`）：scheme 白名单（默认 http/https）、主机非空、端口合法、静态黑名单（deny_hostnames、metadata 地址 169.254.169.254、localhost 类）、deny_cidr_blocks、（生产）目的域名 allowlist。
  - **连接级**（`validate_connection_target`，经自定义 transport 安装）：在真正建连前解析 DNS，逐地址校验非私网/非 metadata/非 deny CIDR，并**固定（pin）已校验的 IP** 用于连接——防御 DNS rebinding（校验时返回公网 IP、连接时解析成内网 IP 的攻击）。
- **拒绝即事件**：任何拒绝产出 `ssrf.*` reason_code 的安全事件，主机名只记摘要。

## 3. 客户端配置（runtime.web.outbound_http_client）

`header{client_name, enabled, mode: sync_http|async_http}` + `detail{timeout_seconds, max_connections, max_keepalive_connections}`（判别联合，mode 与 detail.kind 必须一致）。默认基线：sync_http、5s 超时、64 连接/16 保活。

模式语义：`sync_http` 只装同步客户端（异步资源状态记 stopped）；`async_http` 额外装配共享异步客户端——仅在明确的高并发外部 IO 边界才切换，避免为不存在的并发付出复杂度。

`SharedHttpResourceSet` 同时打包 `RequestExecutionBridge`；HTTP 资源集是热更新可整体替换单元（新配置 → 新连接池 → 原子切换 → 旧池延迟关闭）。

## 4. SSRF 校验细节

拒绝原因码全集（事件与日志中的 `reason_code`）：`ssrf.invalid_scheme`、`ssrf.invalid_port`、`ssrf.empty_host`、`ssrf.blocked_host`、`ssrf.deny_hostname`、`ssrf.host_not_allowed`（allowlist 未命中）、`ssrf.deny_cidr`、`ssrf.non_global_address`（私网/环回/链路本地）、`ssrf.peer_address_mismatch`（连接对端与 pinned IP 不符）、`ssrf.peer_address_unavailable`。

安装点：`install_security_infrastructure` 时对同步/异步客户端分别安装 `SyncOutboundUrlSafetyHook` / `AsyncOutboundUrlSafetyHook`（请求前 URL 校验 + 事件发射，经 contextvar 取当前请求上下文）与 `outbound_url_safety_transport`（连接级校验）。热更新时验证器按新策略重建并重挂钩子。

生产强约束（SettingsSecurityValidator）：策略必须启用、必须拒绝非 global 地址与 metadata、必须启用目的域名 allowlist。开发环境默认拒私网但无 allowlist，便于本地调试。

## 5. 怎么用

```python
http_client = resource_mount.read_runtime_bundle().http_accessor.resource_set.http_client
response = http_client.request("GET", url)   # 钩子与超时自动生效
```

- 在用例中使用：经端口暴露所需的窄能力，不直接传 httpx 对象进应用层。
- 新外部依赖上线：生产环境先把目标域名加入 allowlist 配置，否则全部 `ssrf.host_not_allowed` 拒绝。
- 禁止绕行：`import httpx` 后自建 client/`requests` 直连都会绕过 SSRF 防护，评审必须拦截。

## 6. 注意事项

- URL 校验发生在重定向前的每一跳请求（钩子作用于每个 request），重定向到内网地址同样会被拦。
- DNS pinning 在连接级 transport 中执行；若目标使用短 TTL 轮询 DNS，pinned IP 与后续解析结果不同属正常现象。
- 超时是客户端级统一值；个别慢接口不要全局调大 timeout，而应评估是否走任务化异步处理。
- 关闭策略（`enabled=false`）只允许开发/测试；生产配置校验会拒绝。

## 7. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_outbound_url_safety_unit.py` | 全部 reason_code 分支与 pinning。 |
| unit | `test/unit_test/test_shared_http_resource_unit.py` | 客户端装配与模式分支。 |
| exception | `test/exception_test/*` | 拒绝路径与事件产出。 |
| integration（public_network marker） | `test/integration_test/*` | 真实公网请求路径。 |

## 8. 相关文档

- [项目文档总览](../README.md)
- [安全防护](security_protection.md)
- [运行时资源生命周期](../01_architecture/runtime_resource_lifecycle.md)
