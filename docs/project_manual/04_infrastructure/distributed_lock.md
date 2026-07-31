# 分布式锁

## 1. 这是什么

说明基于缓存原子操作的分布式锁：契约模型、Redis 适配器、获取/续租/释放语义、当前使用场景（密钥族初始化与轮换、IP 封禁写入）及失败关闭边界。

**最后更新范围**：覆盖 `src/core/concurrency_contract/distributed_lock_contract.py` 与 `src/infrastructure/concurrency/distributed_lock_provider.py`。

## 2. 设计思想与动机

多实例部署下，某些操作必须全局单飞：密钥族初始化/轮换，以及同一 IP 的“查活动封禁记录 → 条件新增 → 刷新缓存”。项目选择**缓存原子写实现的租约锁**而不是数据库咨询锁或独立协调服务：生产缓存已经是 Redis，NX + TTL + owner 条件脚本覆盖当前短临界区。

因此它是**协作锁**而非强正确性锁：TTL 到期自动释放（防死锁），持有者崩溃后临界区可能被并发进入——所有使用方的临界区逻辑都要求幂等。

## 3. 契约与实现

- 配置信封（schema `1.0`）：`envelope_kind=distributed_lock_runtime` + `header{kind, schema_version, enabled, policy_name}` + `detail{kind, schema_version, backend=cache, lease_seconds, wait_seconds}`。Pydantic 约束租期 `>=1`、等待 `>=0`、policy 非空并校验三层版本一致。
- 请求：`DistributedLockRequest{namespace, key_digest, owner, lease_seconds, wait_seconds}`；namespace/owner 非空，`key_digest` 至少 12 字符。调用方而非 provider 负责生成摘要与每次获取唯一 owner。
- 锁键：`<runtime.cache.key_prefix>:distributed_lock:<request.namespace>:<key_digest>`，值为 owner。`CacheKeyBuilder` 会拒绝空片段或含 `:` 的片段。
- `RedisDistributedLockAdapter.acquire` 使用 `CacheStore.set_value_if_absent`；首试失败后按 50ms 固定间隔在调用线程阻塞重试，达到单调时钟 deadline 后返回 `None`。
- `DistributedLockProvider.acquire` 不把争用暴露成 `acquired=false`：适配器返回 `None` 时抛出 503 `CACHE_UNAVAILABLE`（消息“分布式锁获取失败”）；底层异常也统一包装为 503（消息“分布式锁不可用”）。成功租约的 `acquired` 才会是 true。
- `release` 使用 owner 条件原子删除；锁已过期或 owner 不匹配时返回 `released=false`，不会误删后继持有人的锁。对 `acquired=false` 的输入原样保持未释放。
- `refresh` 已实现：owner 匹配时原子刷新原租期并返回新的租约快照；已释放/未获取或 owner 不匹配时返回 `acquired=false`。当前生产调用点没有自动 watchdog，也没有调用 `refresh()`。
- `enabled=false` 是固定 **fail-closed**：`acquire()` 直接抛 503，detail 为 `fail_closed`，并非单实例空锁或“总是获得”。

## 4. 当前使用场景

| 场景 | 位置 | 语义 |
| --- | --- | --- |
| 密钥族初始化与轮换 | `KeyManagementService.initialize_key_family` / `rotate_key_family_if_due` | key family SHA-256 为 digest、随机 UUID 为 owner；租期/等待来自 runtime 配置。争用不是“跳过”，而是异常终止本次调用；数据库还有 insert/CAS 防线。 |
| IP 封禁写入 | `IpBlockGuard.block_ip` | IP 摘要直接作为 key_digest、随机 UUID owner、`wait_seconds=0`、租期取 `cache_ttl_seconds`；保护查库、条件新增和缓存刷新。`evaluate()` 的读穿回填不持有该锁，`release_ip()` 也不持有。 |

## 5. 怎么用

```python
lease = lock_provider.acquire(DistributedLockRequest(
    namespace="my_job", key_digest=digest_service.digest(business_key),
    owner=instance_id, lease_seconds=30, wait_seconds=2,
))
try:
    ...  # 幂等临界区，耗时必须显著小于 lease_seconds
finally:
    released_lease = lock_provider.release(lease)
```

争用、禁用和缓存故障都通过 `HttpFaultException` 表达，调用方若要跳过或退避必须显式捕获并按业务语义处理；当前两个生产调用方都不捕获。长临界区可由调用方周期调用 `refresh()`，但必须在返回租约仍 `acquired=true` 时才可继续，且当前没有通用续租循环可复用。

## 6. 注意事项

- 临界区执行时间接近或超过 lease_seconds 会导致锁被他人重入；虽然有显式 `refresh()`，当前实现无 watchdog，长临界区应拆分、由调用方可靠续租或另选机制。
- 锁不可重入：同 owner 二次 acquire 同键会失败（NX 语义），不要嵌套获取。
- 获取等待与 `release/refresh` 都是同步调用；等待循环会阻塞当前请求/worker 线程。没有公平队列，50ms 轮询也不保证先到先得。
- `expires_at_epoch` 这个字段名容易误导：适配器用 `time.monotonic() + lease_seconds` 计算，它是本进程单调时钟域的诊断值，不是 Unix epoch，不能跨进程比较或持久化为墙钟时间。
- provider 名为分布式锁但抽象依赖是任意 `CacheStore`；memory 后端下只能保证单进程线程互斥，生产 Redis 才具备跨进程/跨实例语义。
- 底层 Redis 的 NX、owner 删除和续租由 `SET NX EX` 与 Lua 条件脚本保证原子性；租约本身不提供 fencing token，过期旧持有者仍可能继续写，权威存储必须保留 CAS/唯一约束等二次保护。
- 配置在基线/生产/测试分别为 `10s/0s`、`10s/1s`、`5s/0s`。运行时没有重建 provider 的热更新路径；重载校验会拒绝在线修改，需改配置后重启。`config/app_base.toml` 中还保留 `default_lease_seconds/default_wait_seconds` 旧路径名，判断实际字段应以契约的 `lease_seconds/wait_seconds` 为准。

## 7. 生命周期与资源所有权

锁没有独立网络连接和关闭方法。缓存启动并探活后，`SharedResourceLifecycle.install_security_infrastructure()` 用共享 `CacheStore` 和同一 `key_prefix` 构造 provider，随后初始化启用的密钥族；只有全部成功才将 `shared_distributed_lock`、`shared_key_management` 和 `shared_security_protection` 标为 ready。分布式锁禁用但存在启用密钥族时，启动会在密钥初始化的首次 acquire 处 fail-closed。

停机时任务先停止，随后 `clear_cache_runtime()` 关闭共享 cache store 并清除 provider 引用；锁自身不重复关闭缓存。启动或停机失败沿共享资源 best-effort 释放契约汇总，不会跳过后续数据库/日志释放步骤。

## 8. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| contract | `test/contract_test/test_distributed_lock_contract.py` | 运行时信封、请求/租约字段与版本一致性。 |
| unit | `test/unit_test/test_distributed_lock_provider_unit.py` | 互斥、owner 防误删、续租、过期、缓存不可用与禁用 fail-closed。 |
| integration | `test/integration_test/test_distributed_lock_redis_integration.py` | 真实 Redis 的 TTL、owner、refresh 和故障关闭。 |
| path | `test/path_test/test_key_management_path.py`、`test/path_test/test_security_protection_path.py` | 密钥与 IP 封禁调用链。 |

## 9. 相关文档

- [项目文档总览](../README.md)
- [缓存运行时](cache_runtime.md)
- [安全防护](security_protection.md)
