# 缓存运行时

## 1. 这是什么

详解缓存子系统：`CacheStore` 抽象与 Memory/Redis 两个实现、`CacheService` 的键构建/编解码/命名空间策略、直接使用 `CacheStore` 的安全基础设施，以及缓存从启动探活到停机关闭的资源所有权。

**最后更新范围**：覆盖 `src/core/cache_contract/` 5 个契约文件与 `src/infrastructure/cache/` 实现。

## 2. 设计思想与动机

- **缓存是安全基础设施的地基**：本项目的缓存首要用途不是"加速查询"，而是承载认证节流计数、限流窗口、风险信号、IP 封禁、Token 绑定和租约锁等共享状态。生产环境在 `SettingsSecurityValidator` 与启动器两处拒绝 memory 后端；开发/测试才允许进程内缓存。
- **命名空间 + 策略**：所有键经 `CacheKeyBuilder` 构成 `<key_prefix>:<namespace>:<业务键>`；`CacheNamespace` 枚举（AUTH_THROTTLE、RATE_LIMIT、IP_BLOCK、DISTRIBUTED_LOCK、KEY_RING、TOKEN_BINDING 等）让不同用途隔离、TTL 与故障模式可按命名空间配置（`namespace_policies`）。
- **两层 API 并存**：`CacheService` 提供策略、TTL 和强类型信封，但当前 `CachePayload` 判别联合只包含 `AuthThrottleStatePayload`，生产代码也只有 `AuthFailureThrottle` 使用它。限流、锁、封禁、风险信号、密钥环和 Token 绑定直接使用 `CacheStore` 原子字符串接口；`namespace_policies` 不会自动包住这些直连调用。

## 3. 组件结构

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `CacheStore`（ABC） | `core/cache_contract/cache_store_contract.py` | `get/set/delete`、NX 写、CAS 替换、owner 匹配删除/续期、固定窗口自增与 `close`。 |
| `MemoryCacheStore` | `infrastructure/cache/memory_cache_store.py` | `cachetools.TLRUCache` + `RLock` 的进程内有界实现；`close()` 清空全部项。 |
| `RedisCacheStore` | `infrastructure/cache/redis_cache_store.py` | redis-py 连接池（max_connections、socket_connect_timeout）；启动时 `assert_available()` ping 探活。 |
| `CacheKeyBuilder` | `cache_key_builder.py` | 前缀+命名空间拼键。 |
| `CachePayloadCodec` | `cache_payload_codec.py` | `CacheEnvelope{header,data}` JSON 编解码；当前强类型数据仅覆盖认证节流。 |
| `CachePolicyResolver` | `cache_policy_resolver.py` | 按命名空间解析 TTL 与失败模式（`namespace_policies` 信封 + 运行时默认 TTL 兜底）。 |
| `CacheService` | `cache_service.py` | 面向业务的读/写/删/自增请求对象接口（`CacheReadRequest` 等），组合上述四件。 |

## 4. 配置（runtime.cache）

```toml
[runtime]
backend = "redis"                 # memory | redis；production 文件固定 redis
default_ttl_seconds = 30
key_prefix = "fastapi_web_skeleton"

[runtime.backend_detail]
kind = "redis_cache_backend"      # 必须与 backend 一致
schema_version = "1.0"
redis_url = "redis://:required@redis:6379/0"
socket_connect_timeout_seconds = 5
max_connections = 64
```

基线/测试使用 memory（`max_entries` 分别为 1024/256），生产覆盖为上述 Redis 参数。加载入口是 `AppSettingsLoader` 的分层 TOML 合并与 `CacheRuntimeSettings`：TTL、连接超时、连接数和容量都必须 `>=1`，`key_prefix`/`redis_url` 去空白后不得为空，`backend` 必须和 `backend_detail.kind` 对齐；启动阶段再执行生产 memory 禁令和 Redis `PING`。

`namespace_policies` 是 `CachePolicyEnvelope` 列表，当前契约只允许 `auth_throttle`、`rate_limit`、`query_result` 三类明细且同命名空间不允许重复。TTL 优先级是“请求显式值 → 命名空间默认值 → runtime 默认值”；没有显式策略的命名空间默认 `fail_closed`。但故障模式只由 `CacheService` 解释，不能据此推断直接使用 `CacheStore` 的组件会 fail-open。缓存连接池、前缀、策略均没有热切换实现；重载校验会将相关变更归为需重启或不安全变更并拒绝在线应用。

环境变量覆盖由配置加载器完成，生产部署通常以 `REDIS_URL` 提供真实凭据；仓库 TOML 中的 `required` 只是不可直接投产的占位值。

## 5. 使用方与故障语义

| 使用方 | 命名空间 | 缓存故障时行为 |
| --- | --- | --- |
| `AuthFailureThrottle` | `AUTH_THROTTLE` | 经 `CacheService` 使用固定 `fail_closed` 策略；Redis 的 `CACHE_UNAVAILABLE` 继续上抛为 503。 |
| `RateLimitGuard` | `RATE_LIMIT` | 直接原子自增；缓存错误转换为 503 `CACHE_UNAVAILABLE`，不是“额度超限”的 429。当前 `RateLimitFailMode` 只有 `fail_closed`。 |
| `IpBlockGuard` | `IP_BLOCK` | 缓存未命中/坏值才查数据库；缓存 I/O 失败直接转换为 503，不会在该异常分支回源。 |
| `DistributedLockProvider` | `DISTRIBUTED_LOCK` | NX/owner-CAS 操作失败、争用超时或禁用都 fail-closed 为 503。详见分布式锁文档。 |
| `DatabaseKeyRingStore` | `KEY_RING` | 数据库始终是权威源，成功读取/写入后刷新无 TTL 镜像；缓存刷新失败仍会向调用方传播。当前读取并不先查镜像。 |
| `TokenBindingGuard` / `RiskSignalGuard` | `TOKEN_BINDING` / `RISK_SIGNAL` | 直接使用 store；异常原样向上传播。Token 缓存未命中时 `validate()` 返回匹配，`validate_or_bind()` 建立绑定。 |
| 尚未接入的普通查询 | `QUERY_RESULT` | 契约预留的 `fail_open` 策略：`CacheService` 读按 miss、写/删跳过、自增返回 0；当前没有生产调用点。 |

## 6. 怎么用

需要强类型信封和命名空间策略的新调用，经挂载点取得 `CacheService` 并使用请求对象（方法名以当前实现为准）：

```python
service.write_payload(CacheWriteRequest(namespace=CacheNamespace.AUTH_THROTTLE, key_parts=[...], payload=model))
snapshot = service.read_payload(CacheReadRequest(namespace=..., key_parts=[...], payload_type=Model))
```

新用途至少要：增加/复用 `CacheNamespace`、选择强类型 `CacheService` 或原子 `CacheStore`、明确 TTL 与故障语义、为敏感键片段做摘要。若选择 `CacheService`，还要扩展 `CachePayload` 判别联合；若要配置专属策略，还要扩展 `CachePolicyDetailUnion`，仅添加枚举值并不会让策略自动生效。

## 7. 注意事项

- 键前缀和每个 `key_parts` 都会 `strip()`，不得为空且不得含 `:`；最终键为 `<prefix>:<namespace>:<part...>`。调用方负责在入键前摘要 token、用户名、IP 等敏感原文。
- 内存缓存是单进程的：任何依赖跨实例一致性的功能（节流、限流、锁）在内存后端下语义降级，仅可用于开发与离线测试。`RLock` 只提供当前进程线程间原子性。
- Redis 客户端延迟创建，但启动 `assert_available()` 会创建连接并 `PING`；运行期没有主动健康检查或重连管理线程，redis-py 在每次同步调用中处理连接池行为。所有缓存调用都是同步的，发生在调用线程。
- 自增使用 Lua/进程锁保证“首次写入设置 TTL、窗口内递增不续期”；分布式锁 CAS、owner 删除和续期在 Redis 中也由 Lua 原子完成。
- 载荷 JSON 损坏或读取类型不符时，`CacheService` 记录 warning、尝试按策略删除并返回 miss。对于 fail-closed 命名空间，清理动作的缓存异常仍会传播。
- key_prefix 是多应用共享 Redis 时的隔离手段，改前缀等于清空逻辑缓存（旧键失联自然过期）。

## 8. 生命周期与所有权

`RuntimeResourceBootstrapper` 在 HTTP、数据库和日志就绪后创建缓存；Redis 必须先通过探活。随后同一 `SharedResourceMount` 以该 store 装配认证节流、分布式锁、密钥管理和全部安全守卫，最后才启动消息/任务资源。缓存 store 由挂载点独占持有，不应由业务调用方关闭。

正常停机顺序中任务先停，随后 `clear_cache_runtime()` 调用 `CacheStore.close()` 并清空所有依赖它的锁/密钥/安全引用；数据库和日志仍保留到后续生命周期日志完成落库。启动任一步失败时 FastAPI lifespan 会令 ready=false 并进入同一 best-effort shutdown；释放失败被记录在 `RuntimeResourceReleaseEnvelope.failures`，不会阻止后续资源继续释放。

## 9. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_cache_unit.py` | 键约束、编解码、策略优先级、坏值清理、固定窗口自增与 CAS。 |
| unit | `src/infrastructure/testing/fake_cache_store.py` 支撑的守卫测试 | 故障注入语义。 |
| initialization | `test/initialization_test/test_cache_initialization.py` | 后端选择与生产内存禁令。 |
| path | `test/path_test/test_cache_runtime_path.py` | `CacheService` 策略与运行时路径。 |
| integration | `test/integration_test/test_cache_integration.py` | 真实 Redis 读写、自增与 fail-open/fail-closed。 |

## 10. 相关文档

- [项目文档总览](../README.md)
- [安全防护](security_protection.md)
- [分布式锁](distributed_lock.md)
- [配置系统](configuration_system.md)
