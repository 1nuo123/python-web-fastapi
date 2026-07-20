# 缓存与任务队列体系审查报告

**总体定位**

这套缓存与任务队列体系不是两个彼此孤立的基础设施模块，而是一套围绕运行时资源挂载点统一装配的能力集合。缓存体系负责保存短生命周期、可丢弃或可重建的运行态数据，其中当前最关键的实际使用者是鉴权失败节流；任务队列体系负责把应用层的后台任务命令转换为强类型任务消息，再交给本地执行器或 Funboost/RabbitMQ 后端执行，并用数据库执行记录补齐幂等、追踪、状态流转和失败闭环。

从工程分层看，它们共同遵循同一个设计方向：

1. 配置层描述“启用什么后端、用什么参数、声明哪些任务或缓存策略”。
2. 核心契约层用 Pydantic 模型和抽象接口固定缓存、消息、任务注册、任务执行记录、认证和持久化语义。
3. 基础设施层把内存、Redis、本地消息总线、Funboost、RabbitMQ、SQLAlchemy 仓储等具体技术装配成可运行对象。
4. 应用层只依赖 port，不直接依赖 Redis、RabbitMQ、Funboost 或 ORM。
5. `SharedResourceMount` 是整套体系的运行时总线，负责创建、刷新、替换、关闭和向 API/usecase 暴露这些能力。

**审查方式**

本次按用户要求启动了 4 个有效 `gpt-5.4`、`reasoning_effort=high` 子智能体，分别审查缓存链路、任务队列链路、运行时装配链路、认证与持久化边界。此前还有一轮子智能体因会话中断和服务侧错误失效，已重新补发。最终报告以主线程逐文件审查为主体，并吸收有效子智能体发现。

**一、配置层的功能**

`config/runtime/cache_runtime` 描述缓存运行时，分为 base、production、test 三类覆盖文件。base 默认使用 memory 后端，生产环境切换到 Redis，test 使用更小的内存容量和测试前缀。它的关键配置包括：

- `runtime.cache.backend`：缓存后端，当前支持 `memory` 和 `redis`。
- `runtime.cache.default_ttl_seconds`：未显式指定 TTL 时的默认过期时间。
- `runtime.cache.key_prefix`：所有缓存键统一前缀，用于环境隔离。
- `runtime.cache.backend_detail`：内存最大条目数或 Redis URL/连接超时。
- `runtime.cache.namespace_policies`：按命名空间声明 TTL 和故障模式。

当前已有三个缓存命名空间：`auth_throttle`、`rate_limit`、`query_result`。`auth_throttle` 和 `rate_limit` 都是 `fail_closed`，表示缓存不可用时关键链路不放行；`query_result` 是 `fail_open`，表示普通查询缓存不可用时按未命中处理。生产配置中 `auth_throttle` 的 TTL 提升到 300 秒，并强制走 Redis 后端，和安全配置中“生产鉴权节流必须分布式”的要求一致。

`config/runtime/task_runtime` 描述任务执行后端。当前 base/test 默认使用 `local`，并启用 worker；本地后端明细里保存 `inline_execute_enabled`、重试延迟、退避倍数和最大延迟等参数。Funboost 后端的契约已经存在，但默认配置没有直接切换到 Funboost。`worker_enabled` 只表示当前节点是否消费或执行任务，不再阻断 producer-only 派发。

`config/runtime/message_runtime` 描述消息后端。base 使用 `local`，test/production 使用 `rabbitmq`，并声明 RabbitMQ URL、启动探测、exchange 名称、exchange 类型、持久化、发布确认和确认超时。这里的消息配置主要服务 Funboost/RabbitMQ 后端，而本地任务后端只使用进程内 `LocalMessageBus`。

`config/modules/task_module` 描述任务业务注册清单。它不是运行时后端选择，而是“系统声明了哪些任务、每个任务属于哪个后端、队列名和重试策略是什么”。base/test 声明了 `demo_task` 的本地注册和 `demo_task_funboost` 的 Funboost 注册；development/production 当前只保留禁用的本地 demo 任务。该层还包含 `default_job_kind` 和 `default_retry_limit`，供应用层派发命令缺省使用。

`config/modules/auth_module` 和 `config/runtime/auth_runtime` 虽然不是缓存或任务队列配置，但它们和缓存体系存在明确交叉点：鉴权失败节流由 `auth_runtime` 的失败阈值、失败窗口和锁定时长驱动，实际状态写入 `auth_throttle` 缓存命名空间。`auth_module` 则负责 bootstrap admin 和角色/scope 初始绑定，和队列体系没有直接运行时耦合。

`config/app_base.toml` 把这些配置纳入统一加载白名单。它显式允许 `runtime.cache.*`、`runtime.message.backend`、`runtime.task.*`、`modules.task.*`、`runtime.auth.*` 和 `modules.auth.*` 被配置加载器合并和覆盖，这是缓存、任务和认证配置进入 `ApplicationSettings` 的入口。

**二、缓存核心契约层的功能**

`src/core/cache_contract/cache_namespace_contract.py` 定义缓存命名空间和键分隔符。当前命名空间包括 `AUTH_THROTTLE`、`RATE_LIMIT`、`QUERY_RESULT`，用于避免不同业务状态共享同一键空间。

`src/core/cache_contract/cache_payload_contract.py` 定义缓存值信封。`CacheEntryHeader` 保存 namespace、key、TTL 和 value_kind；`CacheEnvelope` 保存 header 和强类型 data，并校验 header 的 `value_kind` 必须等于 payload 的 `kind`。当前 `CachePayload` 联合类型主要承载 `AuthThrottleStatePayload`，说明缓存实际业务负载还集中在鉴权节流。

`src/core/cache_contract/cache_policy_contract.py` 定义缓存策略信封。它把策略公共头和 detail 分开，并通过 discriminated union 固定三类策略：鉴权节流、通用限流、查询结果。鉴权节流和通用限流的故障模式固定为 `fail_closed`，查询结果允许 `fail_open`。

`src/core/cache_contract/cache_runtime_contract.py` 定义缓存后端运行时契约。它校验外层 `backend` 必须和 `backend_detail.kind` 一致，校验内存容量、Redis URL、连接超时和 key_prefix 的合法性。

`src/core/cache_contract/cache_store_contract.py` 是底层缓存存储抽象。它定义 `get_value`、`set_value`、`increment_with_expire`、`delete_value`、`close`。其中 `increment_with_expire` 是鉴权节流能够正确计数的关键能力。

`src/core/cache_contract/__init__.py` 统一导出缓存契约类型，供基础设施和测试引用。

**三、缓存基础设施层的功能**

`src/infrastructure/cache/cache_key_builder.py` 负责构造统一缓存键。最终键格式是 `key_prefix:namespace:key_part...`。它会拒绝空片段和包含分隔符的片段，避免 key 注入、命名空间穿透和不可预期的键碰撞。

`src/infrastructure/cache/cache_payload_codec.py` 负责把强类型缓存 payload 编码成 JSON 信封，并从 JSON 解码回 `CacheEnvelope`。损坏或不符合信封契约的值会在上层被按未命中处理。

`src/infrastructure/cache/cache_policy_resolver.py` 负责把运行时默认 TTL、命名空间策略和显式 TTL 合并成最终策略。它会拒绝重复命名空间策略。未配置命名空间策略时，默认故障模式是 `fail_closed`。

`src/infrastructure/cache/cache_service.py` 是缓存门面。它统一提供 `write_payload`、`read_payload`、`delete_payload` 和 `increment_counter`。读取时如果发现原始值损坏或 payload 类型不匹配，会删除缓存并返回 miss；缓存不可用时，会按命名空间策略决定 fail-open 还是继续抛出 `CACHE_UNAVAILABLE`。日志只输出缓存键摘要，避免把敏感 key 直接打到日志中。

`src/infrastructure/cache/memory_cache_store.py` 是进程内缓存实现。它使用 `cachetools.TLRUCache` 和 `RLock` 提供 TTL、最大条目数和线程内互斥，适合本地开发、测试或单进程场景。它不是分布式缓存，因此不能承担生产鉴权节流的全局一致性。

`src/infrastructure/cache/redis_cache_store.py` 是 Redis 缓存实现。它惰性创建 Redis 客户端，支持读写、删除、ping 探测，并用 Lua 脚本封装 `INCR + EXPIRE`，保证第一次计数时设置过期时间的原子性。Redis 异常会被转换为统一的 `CACHE_UNAVAILABLE` HTTP 故障。

`src/infrastructure/cache/__init__.py` 是缓存基础设施包导出文件。

**四、缓存真实工作方式**

缓存写入链路是：调用者构造 `CacheWriteRequest`，传入 namespace、key_parts、payload 和可选 TTL；`CacheService` 通过 `CachePolicyResolver` 得出最终 TTL，通过 `CacheKeyBuilder` 构建规范 key，通过 `CachePayloadCodec` 写成信封 JSON，再委托 `CacheStore` 存储。

缓存读取链路是：调用者构造 `CacheReadRequest`，声明期望 payload 类型；`CacheService` 读取原始值，解码信封，检查 data 类型，类型正确则返回 hit，损坏或类型不匹配则删除并返回 miss。

鉴权节流链路是当前最重要的缓存使用场景。`AuthFailureThrottle` 会把用户名或 refresh token 原文先做 SHA-256 摘要，再作为 key_parts 的最后一段，分别维护 counter 和 lock 两类键。失败时通过 `increment_counter` 递增计数；达到阈值后写入 `AuthThrottleStatePayload` 锁状态；成功登录或成功刷新后清理 counter 和 lock。

这条链路的关键设计点是：敏感输入不直接进入缓存键，计数递增是底层缓存原子能力，生产场景应使用 Redis，且 `auth_throttle` 采用 fail-closed，避免缓存故障导致暴力尝试被放行。

**五、任务队列核心契约层的功能**

`src/core/task_contract/task_runtime_contract.py` 定义任务运行时和消息运行时配置契约。它包含 `TaskBackend`、`MessageBackend`、`FunboostBrokerKind`，以及本地任务、Funboost 任务、本地消息、RabbitMQ 消息的 detail 模型。契约强制外层 backend 与内层 detail.kind 一致，并要求 Funboost 当前只能使用 `RABBITMQ_COMPLEX_ROUTING`。

`src/core/task_contract/task_registration_contract.py` 定义任务注册信封。`TaskRegistrationHeader` 描述任务名、job_kind、启用状态和后端；`LocalTaskRegistrationDetail` 保存本地重试次数；`FunboostTaskRegistrationDetail` 保存队列名、exchange、routing key、broker_kind、重试次数、consumer worker、prefetch 和死信 exchange。信封校验 backend 与 detail.kind 必须一致。

`src/core/task_contract/message_bus_contract.py` 定义任务消息。`TaskMessageHeader` 保存 message_id、request_id、trace_id、创建时间；`TaskMessagePayload` 保存 job_kind、deduplication_key、retry_limit、payload_kind、payload_json；`TaskMessageEnvelope` 校验 header 和 payload 的 kind/schema_version 一致。`MessagePublishResult` 用强类型字段表达 published、routed、message_id 和失败原因，`MessageBus` 是发布抽象。

`src/core/task_contract/task_dispatcher_contract.py` 定义派发描述、派发结果和 `TaskDispatcher` 抽象。派发结果会返回 task_id、job_kind、backend、queue_name、是否发布、worker_enabled、执行状态和执行阶段。

`src/core/task_contract/task_execution_record_contract.py` 定义任务执行记录信封。它把状态分为 `PENDING`、`RUNNING`、`RETRYING`、`SUCCESS`、`FAILED`，把阶段分为 dispatch、local_execution、consume_execution、startup_probe。每种状态有独立 detail，并通过 discriminated union 固定结构。

`src/core/task_contract/task_invocation_contract.py` 定义 `TaskInvocationBinding` 和 `TypedTaskInvocation`，用于把原始任务消息解析成“payload 模型 + handler + 原消息”的强类型执行对象。

`src/core/task_contract/task_handler_contract.py` 定义业务处理器抽象，业务任务只需要实现 `handle(invocation)`。

`src/core/task_contract/__init__.py` 统一导出任务契约。

**六、任务队列基础设施层的功能**

`src/infrastructure/task/task_registration_registry.py` 是任务注册中心。它管理配置声明的 registration 和代码绑定的 handler，负责校验重复 job_kind、重复 Funboost 队列、未声明任务、重复 handler、禁用任务、后端不匹配、缺失 handler、payload_model 无效、payload_kind 与 payload_model 不一致、payload_json 反序列化失败。它还可以构造 `TaskBootstrapSnapshot`，用于启动时确认某个后端下启用、禁用和缺 handler 的任务。

`src/infrastructure/task/task_runtime_manager.py` 是任务运行时装配器。它根据 `settings.runtime.task.backend` 选择构建 `LocalTaskDispatcher` 或 `FunboostTaskDispatcher`。handler 完整性校验只在本地 `inline_execute_enabled=true` 或 Funboost `worker_enabled=true` 时触发。Funboost 模式下还会创建 `FunboostTaskBootstrapper`、配置 broker；`worker_enabled=true` 时同步 consumer 并启动消费，`worker_enabled=false` 时只同步 producer-only 发布元数据。

`src/infrastructure/task/local_message_bus.py` 是进程内消息总线，只保存发布过的 `TaskMessageEnvelope` 列表。它适合测试和本地同步执行链路，不提供跨进程持久化。

`src/infrastructure/task/local_task_dispatcher.py` 是本地任务分发器。它先检查当前 job_kind 对应本地后端注册，再预占数据库执行记录；如果记录已存在，则返回 reused_existing_record，避免重复派发。本地是否同进程立即执行 handler 由 `inline_execute_enabled` 控制，`worker_enabled` 只作为节点执行能力展示字段；最终失败时记录 `TaskFailureRecord` 并抛出统一任务失败异常。

`src/infrastructure/task/funboost_task_bootstrapper.py` 是 Funboost 运行时适配器。它把项目内部的 `RegisteredTaskBinding` 转成 Funboost booster/consumer，设置 RabbitMQ complex routing 所需的 queue、exchange、routing key、durable、no_ack、worker 数、retry 等参数。消费者回调中会把 Funboost 收到的消息重新校验为 `TaskMessageEnvelope`，再回到项目统一的 handler 绑定执行。producer-only 节点只注册发布明细，首次 publish 时惰性构建 publisher booster，并把内部 Pydantic 消息转换成 Funboost 需要的字典载荷。

`src/infrastructure/task/funboost_task_dispatcher.py` 是 Funboost 派发器。它会校验目标任务是 Funboost registration，预占执行记录，再通过 bootstrapper 发布消息。它还绑定 Funboost 消费最终失败回调，把耗尽重试后的失败写回执行记录和统一失败回调，并在 shutdown 时释放 Funboost publisher、consumer 和全局 publisher 缓存。

`src/infrastructure/task/rabbitmq_message_gateway.py` 是 RabbitMQ 可用性探测网关。它校验 URL 前缀，构造带 timeout 的连接 URI，并用 `amqpstorm.UriConnection` 做启动探测。探测失败会转换为 `RESOURCE_NOT_READY`。

`src/infrastructure/task/task_execution_store.py` 是任务执行记录门面。它通过 `SharedDbSessionManager` 创建 UoW，再调用 `TaskExecutionRecordRepositoryImpl` 完成 reserve、mark_running、mark_retrying、mark_success、mark_failed，并可以把 ORM 记录转换为强类型 `TaskExecutionRecordEnvelope`。

`src/infrastructure/task/failed_task_recorder.py` 是失败任务内存记录器，并支持 record_listener 回调。当前它更多承担运行期观察和测试支持，真正长期状态由任务执行记录表保存。

`src/infrastructure/task/task_worker_supervisor.py` 是早期或兼容用的 handler 注册容器。当前主链路更偏向 `TaskRegistrationRegistry`，但 supervisor 仍保留注册、查询、替换 binding 的能力。

`src/infrastructure/task/__init__.py` 是任务基础设施包导出文件。

**七、任务队列真实工作方式**

任务派发入口在 `src/application/dispatch_background_job_usecase.py`。调用方传入 `TaskDispatchCommand`，usecase 先从 `TaskRuntimePort` 读取默认 job_kind、当前任务后端、默认 retry_limit，并按当前后端读取启用的任务注册。然后它生成 `TaskDispatchDescriptor` 和 `TaskMessageEnvelope`，最后调用 `dispatch_task_message` 交给运行时。

本地后端链路是：`DispatchBackgroundJobUsecase` -> `SharedResourceMount.dispatch_task_message` -> `LocalTaskDispatcher.dispatch` -> `TaskExecutionStore.reserve` -> `LocalMessageBus.publish` -> 按 `inline_execute_enabled` 决定是否同步执行 handler -> 更新执行记录。本地 worker 开关不再复用为派发拒绝条件；本地是否内联执行由 `inline_execute_enabled` 明确表达。

Funboost/RabbitMQ 后端链路是：启动阶段 `TaskRuntimeManager` 构建 bootstrapper 和 dispatcher；消费节点按注册清单创建 booster/consumer，producer-only 节点只登记发布明细；派发阶段 `FunboostTaskDispatcher` 预占执行记录并发布包装后的 `task_message`；消费阶段 Funboost 取消息，项目回调重新校验消息和 payload，调用 handler，并把执行状态写回数据库；最终失败阶段通过 Funboost failure callback 标记 failed 并触发统一失败记录。

独立 RabbitMQ 消息总线当前使用 `mandatory=true` 发布关键任务消息。exchange 存在但 routing key 无 binding、broker NACK 或 AMQP 异常时，发布会按统一任务失败语义暴露，不再把未路由消息视为成功。启动期还会拒绝 `runtime.task.backend=local` 与 `runtime.message.backend=rabbitmq` 的组合，避免同一任务同时本地执行和外部投递。

执行记录是任务队列体系的关键稳定点。无论本地还是 Funboost，任务都会先 reserve 一条记录，使用 job_kind + deduplication_key 做重复派发控制，再按阶段推进状态。也就是说，任务队列不是只依赖消息中间件“发出去就算成功”，而是把可追踪、可幂等、可查询的执行事实落在数据库中。

**八、认证访问边界与缓存/队列的关系**

`config/modules/auth_module` 定义鉴权模块业务开关和 bootstrap admin 初始角色绑定。它和任务队列没有直接耦合，和缓存的关系也不是配置级直接引用，而是通过 `auth_runtime` 的节流参数影响 `AuthFailureThrottle`。

`config/runtime/auth_runtime` 定义 JWT、安全令牌和鉴权失败节流参数，包括 access/refresh 过期时间、刷新令牌轮换、登录失败阈值、登录失败窗口、刷新失败阈值、刷新失败窗口、锁定时间。节流状态实际落在缓存系统 `auth_throttle` 命名空间。

`src/api/endpoint_auth_access/contract_auth_access.py` 定义登录、刷新、撤销接口的请求体模型。

`src/api/endpoint_auth_access/route_auth_access.py` 暴露 `/auth/token`、`/auth/refresh`、`/auth/revoke`、`/auth/me`。前三个接口通过 request execution bridge 执行同步 usecase，`/auth/me` 依赖认证中间件绑定的 principal，并通过 route-level requirement 调用授权守卫。

`src/api/authorization_guard.py` 是路由授权守卫。它只依赖最小运行时 port 获取 `AuthorizationPolicyEvaluator`，把 `RouteAuthorizationRequirement` 转为 policy，并在不满足角色/scope 时抛出 403。它不直接使用缓存或队列。

`src/application/ports/auth_runtime_port.py` 定义鉴权 usecase 所需能力：节流器、UoW、身份仓储、refresh token 仓储、密码哈希器、JWT 服务。这里把应用层和具体缓存/数据库/JWT 实现隔离开。

`src/application/ports/task_runtime_port.py` 定义任务 usecase 所需能力：读取当前后端、默认任务、默认重试、指定后端任务注册、派发任务消息。它是任务体系的应用层边界。

`src/application/ports/settings_reader_port.py` 定义设置快照读取能力，供健康检查、系统概览等模块读取运行态配置。

`src/application/ports/application_port_contract.py` 定义应用端口本身的契约描述，当前包括 auth runtime、settings reader、task runtime 三类 port 声明。

`src/core/auth_contract` 是认证语义中心。它定义 principal、授权策略、身份授权快照、身份状态、节流状态、bootstrap 角色绑定、refresh token 失效命令、token payload、token issue/revoke payload、token session 状态。缓存体系直接复用其中的 `AuthThrottleStatePayload` 作为缓存 payload。

`src/core/persistence_contract` 是持久化边界。`AuthIdentityRepository` 提供身份、授权快照和密码哈希更新能力；`RefreshTokenRepository` 提供 refresh token session 创建、加锁读取、轮换、撤销、状态查询和批量失效能力；`UnitOfWork` 定义事务边界；`Repository` 定义基础仓储。认证中间件、登录、刷新、撤销都通过这些契约回库，不依赖缓存保存授权真值。

`src/domain/auth` 保存稳定领域语义：`AuthErrorCode`、`AuthRoleKey`、`AuthScopeCode`、`AccessTokenPolicy`。它和缓存/队列没有技术耦合，但缓存节流、API 响应和授权守卫会复用这些领域枚举。

`src/infrastructure/auth/auth_failure_throttle.py` 是认证和缓存最直接的交叉文件。它用 `CacheService` 保存失败计数和锁定状态，并把用户名或 refresh token 摘要化后进入缓存键。

`src/infrastructure/auth/jwt_token_service.py`、`password_hasher.py`、`oauth2_scheme_provider.py`、`authorization_policy_evaluator.py`、`bootstrap_admin_synchronizer.py` 分别负责令牌签发/解码、密码哈希、Bearer 提取、角色/scope 策略判断、启动期 admin/role/scope 同步。它们本身不依赖任务队列；其中节流器以外的认证能力也不依赖缓存。

`src/infrastructure/middleware_chain/authentication_binding_middleware.py` 是受保护请求的认证绑定入口。它解析 Bearer access token，回库读取当前授权快照和 token session 状态，然后把 `AuthenticatedPrincipal` 绑定到 request state。该中间件刻意不信任 token 内的旧角色/scope，而是以数据库为授权真值。它没有走缓存读取授权，这提高了权限回收的即时性，但也意味着受保护请求会产生数据库读压力。

**九、资源挂载、注册与应用装配层的功能**

`src/infrastructure/shared_resource_mount.py` 是缓存、任务、认证、数据库、日志、HTTP 客户端等资源的核心挂载点。它初始化 password hasher、JWT service、授权评估器、授权守卫、任务运行时管理器、失败任务记录器、任务注册中心、缓存 store/service、任务执行 store 等对象。它实现了 `AuthRuntimePort`、`TaskRuntimePort`、`SettingsReaderPort` 等上层需要的能力，并负责 settings apply 时刷新缓存、任务注册和运行时资源。

`SharedResourceMount.startup()` 通过 resource bootstrapper 启动运行时资源；`shutdown()` 通过 resource releaser 关闭缓存、任务 dispatcher、HTTP 客户端和数据库资源。它还提供 `get_cache_store`、`get_cache_service`、`get_task_dispatcher`、`get_task_registration_registry`、`dispatch_task_message`、`create_unit_of_work`、`create_auth_identity_repository`、`create_refresh_token_repository` 等访问器。

`src/infrastructure/resource_mount/runtime_resource_bootstrapper.py`、`runtime_accessor_refresher.py`、`runtime_resource_releaser.py`、`runtime_resource_mount_contract.py` 共同承担资源启动、访问器刷新、释放和状态契约。它们让缓存、任务、数据库、日志等资源在 settings 变更时能被成组替换，而不是散落在路由或 usecase 中自行 new 对象。

`src/infrastructure/settings/app_settings_loader.py` 是配置装载中心。它定义原始 mapping 类型、模块 settings、运行时 settings，并把缓存、消息、任务、认证配置解析成强类型 `ApplicationSettings`。其中 `CacheRuntimeSettings`、`MessageRuntimeSettings`、`TaskRuntimeSettings`、`AuthRuntimeSettings`、`TaskModuleSettings` 是本报告关注的核心配置模型。

`src/infrastructure/settings/parsers/runtime_settings_parser.py` 和 `module_settings_parser.py` 负责把 `config/runtime/*` 和 `config/modules/*` 的 TOML 内容读入统一层级。

`src/infrastructure/settings/settings_security_validator.py` 负责生产安全基线校验。它会在生产环境约束 JWT secret、bootstrap admin、分布式鉴权节流、内存缓存、RabbitMQ/Funboost 等安全条件，是缓存和任务配置进入生产前的最后一道校验。

`src/infrastructure/settings/settings_reload_coordinator.py`、`settings_apply_transaction.py`、`settings_apply_contract.py`、`settings_snapshot_store.py` 负责配置热更新、事务化 apply、apply 结果契约和快照保存。任务注册刷新使用 `TaskRegistryReloadDetail` 表达结果。

`src/infrastructure/fastapi_app_assembler.py` 是应用装配器。它加载 settings，校验 Web 模块启用清单，创建 `SharedResourceMount`，注册任务 binding，构建 usecase 和 route composer，并把 resource mount 放入 app container。这里是缓存、任务和认证真正进入 FastAPI 应用的入口。

`src/infrastructure/fastapi_lifespan_orchestrator.py` 把 FastAPI 生命周期绑定到 `SharedResourceMount.startup/shutdown`。缓存 Redis 连接、任务 dispatcher、Funboost consumer、数据库连接等资源都依赖这个生命周期被正确准备和释放。

`src/infrastructure/fastapi_route_composer.py` 负责按启用模块挂载 router。缓存和任务本身没有独立 HTTP 模块，认证访问模块通过 Web bundle 挂载。

`src/api/web_module_manifest.py` 声明内置 Web 模块，包括 health、auth_access、system_overview。`auth_access` 的 provider import path 指向 `src.api.endpoint_auth_access.route_auth_access.AuthAccessBundleProvider`。

`src/api/web_bundle_catalog.py` 加载并校验 Web bundle provider，确保 manifest 与 provider 输出的 module_name 一致，并校验启用模块必须存在。

`src/api/task_binding_provider.py` 当前返回空 binding 列表，说明项目默认没有业务任务 handler 绑定；测试或调用方需要显式传入 task_bindings，否则启用的任务注册可能因为缺 handler 而启动失败。该空实现是快速开发骨架的业务扩展占位设计，不是遗漏实现。

`src/main.py` 是 ASGI 入口，通过应用工厂/装配器创建实际 FastAPI app。

**十、持久化层与执行记录**

`src/infrastructure/persistence/repository_impl/task_execution_record_repository_impl.py` 是任务执行记录仓储实现。它支撑 reserve/upsert、按 job_kind + deduplication_key 查询、按字段更新等能力，是本地和 Funboost 任务幂等控制的基础。

`src/infrastructure/persistence/orm_model/task_execution_record_orm_model.py` 是任务执行记录 ORM 模型，承载 task_id、job_kind、deduplication_key、backend、status、stage、attempt_count、queue_name、payload_kind、payload_json、request_id、trace_id、错误信息和时间戳。

`src/infrastructure/persistence/repository_impl/auth_identity_repository_impl.py`、`refresh_token_repository_impl.py` 与 `orm_model/auth_*.py` 支撑认证回库真值、refresh token session 生命周期和授权快照。它们不属于任务队列核心，但属于用户指定的认证边界文件，也是缓存节流之外认证体系的状态真值来源。

`src/infrastructure/persistence/alembic/versions/202605221609_create_task_execution_record_table.py` 和 `202605231821_add_task_execution_backend.py` 对应任务执行记录表和 backend/stage 等字段演进。`202605151600_create_auth_tables.py`、`202605251640_harden_refresh_token_constraints.py` 对应认证表和 refresh token 约束加固。

**十一、关键文件任务与作用清单**

缓存配置文件：

- `config/runtime/cache_runtime/cache_runtime_base.toml`：默认内存缓存、默认 TTL、key_prefix、三类 namespace policy。
- `config/runtime/cache_runtime/cache_runtime_production.toml`：生产 Redis 后端、Redis URL、连接超时、生产 TTL 和 fail-open/fail-closed 策略。
- `config/runtime/cache_runtime/cache_runtime_test.toml`：测试 key_prefix、内存容量和测试 TTL 覆盖。

任务与消息配置文件：

- `config/runtime/task_runtime/task_runtime_base.toml`：默认本地任务后端和 worker_enabled。
- `config/runtime/task_runtime/task_runtime_test.toml`：测试本地任务后端覆盖。
- `config/runtime/message_runtime/message_runtime_base.toml`：默认本地消息后端。
- `config/runtime/message_runtime/message_runtime_test.toml`：测试 RabbitMQ 后端参数和探测开关。
- `config/runtime/message_runtime/message_runtime_production.toml`：生产 RabbitMQ URL、exchange、持久化和发布确认。
- `config/modules/task_module/task_module_base.toml`：默认 demo 本地任务和 demo Funboost 任务注册。
- `config/modules/task_module/task_module_development.toml`：开发环境禁用 demo 本地任务。
- `config/modules/task_module/task_module_production.toml`：生产环境禁用 demo 本地任务。
- `config/modules/task_module/task_module_test.toml`：测试环境启用 demo 本地任务和 demo Funboost 任务。
- `funboost_config.py`：Funboost 全局配置覆盖入口，当前只继承默认连接和公共配置。

认证相关配置文件：

- `config/modules/auth_module/auth_module_base.toml`：默认关闭 bootstrap admin，角色绑定为空。
- `config/modules/auth_module/auth_module_development.toml`：开发环境启用 bootstrap admin 和默认角色/scope 绑定。
- `config/modules/auth_module/auth_module_test.toml`：测试环境启用 bootstrap admin 和测试角色/scope 绑定。
- `config/runtime/auth_runtime/auth_runtime_base.toml`：JWT、access/refresh TTL、刷新轮换和失败节流默认参数。
- `config/runtime/auth_runtime/auth_runtime_test.toml`：测试环境缩短 refresh TTL 和失败窗口。

缓存代码文件：

- `src/core/cache_contract/cache_namespace_contract.py`：缓存命名空间和 key 分隔符。
- `src/core/cache_contract/cache_payload_contract.py`：缓存信封和 payload 契约。
- `src/core/cache_contract/cache_policy_contract.py`：命名空间策略、TTL 和故障模式契约。
- `src/core/cache_contract/cache_runtime_contract.py`：memory/redis 后端运行时契约。
- `src/core/cache_contract/cache_store_contract.py`：缓存存储抽象接口。
- `src/infrastructure/cache/cache_key_builder.py`：规范化构造缓存 key。
- `src/infrastructure/cache/cache_payload_codec.py`：缓存 payload JSON 编解码。
- `src/infrastructure/cache/cache_policy_resolver.py`：按显式 TTL、namespace policy、runtime 默认值解析最终策略。
- `src/infrastructure/cache/cache_service.py`：缓存读写删、计数、损坏值清理和 fail-open/fail-closed 门面。
- `src/infrastructure/cache/memory_cache_store.py`：进程内 TTL 缓存实现。
- `src/infrastructure/cache/redis_cache_store.py`：Redis 缓存实现和原子递增脚本。

任务队列代码文件：

- `src/application/dispatch_background_job_usecase.py`：应用层后台任务派发入口。
- `src/application/ports/task_runtime_port.py`：任务运行时 port。
- `src/core/task_contract/message_bus_contract.py`：任务消息信封和消息总线抽象。
- `src/core/task_contract/task_dispatcher_contract.py`：任务派发描述、结果和 dispatcher 抽象。
- `src/core/task_contract/task_execution_record_contract.py`：任务执行记录状态/阶段信封。
- `src/core/task_contract/task_handler_contract.py`：业务任务 handler 抽象。
- `src/core/task_contract/task_invocation_contract.py`：强类型任务执行对象。
- `src/core/task_contract/task_registration_contract.py`：任务注册信封。
- `src/core/task_contract/task_runtime_contract.py`：任务/消息后端运行时契约。
- `src/infrastructure/task/task_registration_registry.py`：任务注册、handler 绑定和 payload 校验中心。
- `src/infrastructure/task/task_runtime_manager.py`：local/funboost 运行时装配器。
- `src/infrastructure/task/local_message_bus.py`：进程内消息总线。
- `src/infrastructure/task/local_task_dispatcher.py`：本地任务派发和同步执行器。
- `src/infrastructure/task/funboost_task_bootstrapper.py`：Funboost booster/consumer 构建和 RabbitMQ routing 参数适配。
- `src/infrastructure/task/funboost_task_dispatcher.py`：Funboost 派发、失败回调和资源释放。
- `src/infrastructure/task/rabbitmq_message_gateway.py`：RabbitMQ 配置校验和可用性探测。
- `src/infrastructure/task/task_execution_store.py`：任务执行记录门面。
- `src/infrastructure/task/failed_task_recorder.py`：失败任务内存记录和 listener。
- `src/infrastructure/task/task_worker_supervisor.py`：任务 handler 注册容器。

认证边界代码文件：

- `src/api/endpoint_auth_access/contract_auth_access.py`：登录/刷新/撤销请求体。
- `src/api/endpoint_auth_access/route_auth_access.py`：认证 HTTP 路由和 AuthAccess bundle provider。
- `src/api/authorization_guard.py`：路由级授权守卫。
- `src/application/ports/auth_runtime_port.py`：认证 usecase 所需 port。
- `src/application/ports/settings_reader_port.py`：配置快照读取 port。
- `src/application/ports/application_port_contract.py`：应用 port 契约描述。
- `src/core/auth_contract/*.py`：principal、policy、token、session、throttle、bootstrap 等认证契约。
- `src/core/persistence_contract/*.py`：认证仓储、refresh token 仓储、UoW 和基础 repository 契约。
- `src/domain/auth/*.py`：认证错误码、角色、scope 和 access token policy。
- `src/infrastructure/auth/auth_failure_throttle.py`：鉴权失败节流，直接依赖缓存体系。
- `src/infrastructure/auth/jwt_token_service.py`：JWT 签发和解码。
- `src/infrastructure/auth/password_hasher.py`：密码哈希与 rehash 判断。
- `src/infrastructure/auth/oauth2_scheme_provider.py`：Bearer token 提取。
- `src/infrastructure/auth/authorization_policy_evaluator.py`：角色/scope 授权判断。
- `src/infrastructure/auth/bootstrap_admin_synchronizer.py`：启动期默认管理员与角色/scope 同步。

装配与注册文件：

- `src/infrastructure/shared_resource_mount.py`：缓存、任务、认证、数据库等运行时资源总线。
- `src/infrastructure/resource_mount/*.py`：资源启动、刷新、释放和状态契约。
- `src/infrastructure/settings/app_settings_loader.py`：配置加载和强类型 settings 聚合。
- `src/infrastructure/settings/settings_security_validator.py`：生产安全基线校验。
- `src/infrastructure/settings/settings_reload_coordinator.py`：配置热更新协调。
- `src/infrastructure/settings/settings_apply_transaction.py`：配置应用事务。
- `src/infrastructure/settings/settings_apply_contract.py`：settings apply 结果契约。
- `src/infrastructure/fastapi_app_assembler.py`：应用、resource mount、usecase、router 和任务 binding 装配。
- `src/infrastructure/fastapi_lifespan_orchestrator.py`：FastAPI 生命周期和 resource mount 生命周期绑定。
- `src/infrastructure/fastapi_route_composer.py`：Web bundle 路由挂载。
- `src/api/web_module_manifest.py`：内置 Web 模块 manifest。
- `src/api/web_bundle_catalog.py`：Web bundle provider 加载和校验。
- `src/api/task_binding_provider.py`：应用任务 binding 提供器，当前为空实现。
- `src/main.py`：应用入口。

持久化相关文件：

- `src/infrastructure/persistence/repository_impl/task_execution_record_repository_impl.py`：任务执行记录仓储实现。
- `src/infrastructure/persistence/orm_model/task_execution_record_orm_model.py`：任务执行记录 ORM。
- `src/infrastructure/persistence/repository_impl/auth_identity_repository_impl.py`：认证身份仓储实现。
- `src/infrastructure/persistence/repository_impl/refresh_token_repository_impl.py`：refresh token session 仓储实现。
- `src/infrastructure/persistence/orm_model/auth_user_orm_model.py`：用户 ORM。
- `src/infrastructure/persistence/orm_model/auth_role_orm_model.py`：角色 ORM。
- `src/infrastructure/persistence/orm_model/auth_role_scope_orm_model.py`：角色 scope ORM。
- `src/infrastructure/persistence/orm_model/auth_user_role_orm_model.py`：用户角色绑定 ORM。
- `src/infrastructure/persistence/orm_model/auth_refresh_token_orm_model.py`：refresh token session ORM。
- `src/infrastructure/persistence/alembic/versions/*task*.py`：任务执行记录表结构迁移。
- `src/infrastructure/persistence/alembic/versions/*auth*.py`：认证表结构迁移和 refresh token 约束加固。

**十二、测试覆盖证据**

缓存测试覆盖较完整：

- `test/unit_test/test_cache_unit.py` 覆盖 key builder、payload codec、policy envelope、TTL 解析、类型不匹配清理、原子递增、敏感主体摘要化。
- `test/path_test/test_cache_runtime_path.py` 覆盖缓存运行时配置错误路径、namespace policy 加载、损坏原始值清理和 TTL 过期路径。
- `test/initialization_test/test_cache_initialization.py` 覆盖应用启动时内存/Redis 缓存资源准备。
- `test/integration_test/test_cache_integration.py` 覆盖 Redis 读写过期、Redis 鉴权节流锁定、Redis 并发递增不丢计数。

任务测试覆盖的关键点包括：

- `test/unit_test/test_task_registration_registry_unit.py` 覆盖任务注册、重复、缺 handler、payload 校验等注册中心行为。
- `test/unit_test/test_local_task_dispatcher_unit.py` 覆盖本地 dispatcher、执行和重试行为。
- `test/unit_test/test_funboost_task_dispatcher_unit.py` 覆盖 Funboost 派发和失败处理适配。
- `test/unit_test/test_rabbitmq_message_gateway_unit.py` 覆盖 RabbitMQ URL 和可用性探测。
- `test/unit_test/test_task_execution_record_repository_unit.py` 覆盖执行记录仓储。
- `test/integration_test/test_task_execution_record_integration.py` 覆盖执行记录状态流转持久化。
- `test/contract_test/test_task_registration_contract.py` 和 `test/contract_test/test_task_execution_contract.py` 覆盖任务注册与执行记录契约。
- `test/path_test/test_task_runtime_path.py` 与 `test/initialization_test/test_task_runtime_initialization.py` 覆盖任务运行时配置和启动路径。
- `test/boundary_test/test_task_execution_boundary.py` 覆盖执行记录 detail 和重试延迟边界。

认证交叉测试包括：

- `test/unit_test/test_auth_persistence_unit.py` 覆盖认证仓储。
- `test/contract_test/test_refresh_token_invalidation_contract.py` 覆盖 refresh token 失效命令。
- `test/interface_test/test_security_http_interface.py`、`test/boundary_test/test_security_boundary.py`、`test/integration_test/test_security_production_integration.py` 覆盖认证安全边界。
- `test/convention_usage_test/test_end_to_end_usage.py` 串联登录、刷新、撤销、受保护路由和任务派发，证明认证、任务和装配链路能在约定用法下闭环。

**十三、风险与缺口**

1. 已修正：`MemoryCacheStore.increment_with_expire` 和 `RedisCacheStore.increment_with_expire` 的窗口语义已统一为固定窗口。当前语义是首次递增设置 TTL，窗口内后续递增只更新计数、不刷新 TTL；鉴权失败节流在 memory 与 Redis 后端下不再因计数窗口刷新策略产生漂移。

2. `cache_runtime` 里 `auth_throttle.default_ttl_seconds` 对当前鉴权节流基本不生效。`AuthFailureThrottle` 对 counter 和 lock 都显式传入 `runtime.auth` 中的失败窗口和锁定时间，而 `CachePolicyResolver` 又是显式 TTL 优先，所以节流时间窗口真正由 `auth_runtime` 驱动，不是由 `cache_runtime` 的该命名空间 TTL 驱动。配置语义需要文档化或收敛。

3. `SharedResourceMount.apply_settings()` 当前对缓存热更新不完整。启动阶段会完整创建 `CacheStore -> CacheService -> AuthFailureThrottle`，但 settings apply 路径主要重建 `AuthFailureThrottle`，没有同步替换 cache backend、key_prefix 或 namespace policy。若运行中修改 `runtime.cache.*`，实际缓存行为可能仍保持旧值。

4. 启动失败路径存在资源遗留风险。`SharedResourceMount.startup()` 在异常路径标记失败状态后重新抛出，但没有立即回收已初始化资源。如果失败发生在 RabbitMQ 探测、任务绑定校验等后段步骤，前面已创建的 HTTP、DB、日志、缓存资源可能停留到进程结束或外层显式 shutdown。

5. 任务热重载不是完全原子。`apply_settings()` 构建候选任务运行时时可能已经创建 Funboost bootstrapper，并在 `worker_enabled` 时提前启动 consumer；旧 dispatcher 则到提交阶段才关闭。这样会出现短时间双消费者或回滚前已有副作用的窗口。

6. 已标注：多组 RabbitMQ/Funboost 配置字段已建模但未全部落到执行链路。当前真实生效字段包括 RabbitMQ URL、消息启动探测、RabbitMQ mandatory 发布、exchange type/durable、任务级 queue、broker_kind、consumer_worker_count、retry_limit、exchange_name、routing_key、`worker_enabled` 与 `inline_execute_enabled`；registration 级 `prefetch_count`、`dead_letter_exchange` 等仍按快速开发阶段预留字段处理。

7. 认证边界进入任务队列后丢失主体身份。`task:dispatch` 已存在于默认 scope 体系中，但 `TaskDispatchCommand`、`TaskMessageEnvelope`、任务执行记录 ORM 都没有 `subject_id`、角色快照或授权快照字段。任务记录只能靠 request_id/trace_id 做链路关联，不能独立表达“谁发起了这次受权调度”。

8. 已标注：`src/api/task_binding_provider.py` 当前返回空列表是业务任务绑定扩展占位。默认配置中 base/test 存在启用任务注册，如果应用启动没有外部传入 task_bindings，任务运行时会因为启用任务缺 handler 而失败；真实业务项目应在该 provider 或测试工厂中显式注入 `RegisteredTaskBinding`。

9. 当前缓存 payload 联合类型主要只有 `AuthThrottleStatePayload`。`rate_limit` 和 `query_result` 命名空间已有策略，但实际强类型 payload 尚未扩展。后续如果要缓存查询结果，需要先补齐 payload contract，否则会退化为临时字符串或绕过统一信封。

10. 受保护请求认证绑定不缓存授权快照和 token session 状态，每次有效 Bearer 都会回库。这个设计有利于权限回收即时生效，但高并发下需要数据库容量评估。若后续引入授权缓存，必须处理撤权、禁用、session revoke 的失效策略。

11. 登录和刷新把缓存可用性纳入认证可用性边界。`/auth/token` 和 `/auth/refresh` 一开始就读取 `AuthFailureThrottle`；如果缓存资源未挂载，会直接走 `RESOURCE_NOT_READY`，而不是降级为无节流。考虑到当前节流策略是安全关键链路 fail-closed，这个行为可以成立，但需要明确写入运行手册。

12. 刷新令牌持久化同时绑定 `user_id` 和 `subject_id`，bootstrap admin 同步又会写回 subject_id。若 subject_id 被改动，活跃 refresh session 可能出现外键或会话主体一致性风险。

13. 禁用账户在刷新链路上不会进入缓存节流计数，和登录链路不一致。登录会把不存在、禁用、密码错误统一记失败；刷新链路对禁用账户直接返回账户禁用，未累计 refresh 失败次数。

14. 本地任务后端的 `LocalMessageBus` 是有界进程内列表，只保留容量上限内的最新消息，不具备重启恢复能力。`inline_execute_enabled=false` 时本地任务只完成派发与记录，不在当前进程执行 handler。它适合开发测试，不应被误认为可靠队列。

15. Funboost/RabbitMQ 链路已经有发布、消费、失败回调和 shutdown 释放逻辑，但真实生产可观测性仍主要依赖任务执行记录和日志。若业务任务增多，需要补充队列深度、消费延迟、重试耗尽、死信队列等指标。

16. `FailedTaskRecorder` 是内存记录器。最终状态已落库，但内存失败列表本身不具备长期可靠性。报告和监控应以任务执行记录表为准。

17. Redis、RabbitMQ、Postgres 相关测试依赖外部服务地址。子智能体实际尝试任务测试时卡在 `test/conftest.py` 的 Postgres 准备阶段，说明本机如果没有测试数据库，部分本可纯内存的单测也无法直接进入测试主体。CI 需要明确服务编排策略。

**十四、总体结论**

当前缓存体系已经形成“契约、策略、门面、内存实现、Redis 实现、装配和测试”的完整闭环。它的设计重心不是泛化缓存所有业务数据，而是先把安全敏感的鉴权失败节流做好：键规范化、敏感输入摘要化、Redis 原子递增、命名空间 TTL、fail-closed 策略和生产安全校验都已经具备。

当前任务队列体系也已经形成“注册声明、handler 绑定、强类型消息、派发、执行记录、本地后端、Funboost/RabbitMQ 后端、失败闭环”的完整骨架。它最重要的工程价值是把任务执行事实落到数据库执行记录中，使本地执行和消息队列执行都能共享状态流转、幂等控制和追踪语义。

认证体系和缓存/队列的关系边界比较清晰：认证失败节流直接使用缓存；认证授权真值仍来自数据库；认证 API 和授权守卫不依赖任务队列；任务队列可以被已认证业务链路调用，但队列本身不承载认证状态。

如果用一句话概括：这套体系已经具备从配置到运行时装配、从本地开发到 Redis/RabbitMQ 生产后端、从强类型契约到测试证据的完整骨架；后续真正需要补的是业务任务 binding 的默认接入示例、更多缓存 payload 类型、生产队列观测指标以及资源热替换时的运行中任务平滑性验证。

**十五、2026-05-26 轻量修正回归**

本轮按快速开发规格完成三项轻量修正：memory/Redis 计数窗口统一为固定窗口；`task_binding_provider.py` 明确为空实现占位；Funboost/RabbitMQ 字段区分为当前已生效字段与预留字段。

真实测试已覆盖缓存单元测试、任务运行时路径测试、Funboost 派发单元测试、Redis 集成测试和任务/缓存相关回归测试。测试过程中 Docker 端口代理出现 Postgres、RabbitMQ、Redis 连接关闭或超时，重启对应服务后回跑通过；未发现需要回退源码或契约的测试失败。

**十六、2026-06-20 统一心智模型整改回归**

本轮任务运行时收口为：`worker_enabled` 表示消费/执行节点开关，`inline_execute_enabled` 表示本地同进程执行开关；Funboost producer-only 节点允许发布且惰性创建 publisher booster；RabbitMQ 消息总线使用 `mandatory=true` 并暴露未路由失败；`local + rabbitmq` 拓扑在启动期拒绝。

本轮同时回归后台受保护 scope、IP 封禁事件、日志 lazy flush、admin audit operation 与分布式锁 fail-closed 文档。真实测试在 Docker Compose 启动后完成：最小失败集全部通过，依赖型集成测试 `13 passed, 61 warnings`，全量 `.\.venv\Scripts\python.exe -m pytest -q -rs` 通过，结果为 `620 passed, 62 warnings`。
