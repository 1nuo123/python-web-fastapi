# Funboost + RabbitMQ 任务队列基建完善执行方案

## 任务目标
最终要交付一套符合当前项目分层架构的任务队列基建，完成 `funboost + RabbitMQ` 真实接入，并补齐“任务注册机制 + 每个任务独立配置 + 显式装配 + 可测试回归”的完整链路。

完成判定是：当前仅有的 `LocalTaskDispatcher + RabbitMqMessageGateway 配置校验 + funboost 预留位` 被升级为可注册、可配置、可装配、可真实运行、可回归验证的任务基建；源码、测试、文档三者一致。

## 全局约束
- 以当前源码为准；若 `docs`、设计稿、历史执行方案与源码冲突，按源码执行，并在文档回归中标注历史文档可能过期。
- 严格保持当前分层边界：`src/core` 只定义契约，`src/infrastructure` 只落地实现，`src/infrastructure/settings/app_settings_loader.py` 仍是唯一配置收口点，`src/infrastructure/shared_resource_mount.py` 仍是唯一装配入口。
- 任务注册、任务运行时配置、任务结果契约统一采用“公共头字段 + 强类型扩展字段”规则；扩展字段必须使用 Pydantic 判别联合，必须包含 `kind`、`schema_version`，必须启用 `extra="forbid"`。
- 禁止在任务注册、任务运行时扩展、任务派发扩展中使用 `dict[str, Any]`、`metadata`、`extra_payload`；外层类型与内层扩展类型必须一致。
- 任务注册必须显式、可枚举、可校验，禁止仅靠导入副作用隐式注册；允许保留兼容包装层，但真实装配必须落到统一注册中心。
- `local` 后端继续保留，作为单机回退与测试路径；`funboost + RabbitMQ` 作为新增真实后端，不能破坏现有本地链路。
- 任务派发、任务执行、失败记录、资源健康检查要分层收口；日志与异常信息统一中文，禁止新增散落式 `print`。
- 测试必须遵循 `docs/standard/测试规范.md`；新增能力至少覆盖 contract、unit、path、boundary、exception、initialization、integration、convention usage 中的合理子集。
- 真实 RabbitMQ 依赖必须纳入工程化运行环境，不能停留在“只校验 URL、不启动 broker”的占位状态。

## 验收标准
- `runtime.task.backend = "funboost"` 且消息后端指向 RabbitMQ 时，任务可完成真实发布、消费、重试、失败记录闭环。
- 任务注册清单支持启动期校验；重复 `job_kind`、重复队列、未知后端、禁用任务误派发、未绑定处理器等场景都能快速失败并给出清晰错误。
- 每个任务都能拥有独立配置，且全局默认项与任务级覆盖项边界清晰，配置类型安全，`extra="forbid"` 生效。
- 现有 `DispatchBackgroundJobUsecase`、`SharedResourceMount`、`TaskWorkerSupervisor`、`LocalTaskDispatcher` 的调用链被收口到注册中心，不再依赖裸字符串字典式处理器挂载。
- `compose.yml`、运行时配置、真实测试入口、设计文档与源码一致；不再出现“funboost 已支持但实际上只有占位”的文档偏差。
- 受影响测试分组与全量回归通过。

## 生命周期
1. 执行修改
2. 新增或修改测试
3. 真实测试
4. 回归修复
5. 文档回归

## 总任务清单
- [x] 执行修改
- [x] 新增或修改测试
- [x] 真实测试
- [x] 回归修复
- [x] 文档回归

## 阶段依赖关系
- Phase 1 先完成任务注册契约、任务运行时契约与配置收口，后续实现都依赖这组稳定边界。
- Phase 2 依赖 Phase 1，在统一契约之上完成注册中心、装配入口、派发解析与本地兼容。
- Phase 3 依赖 Phase 1 与 Phase 2，在真实注册链路上接入 `funboost + RabbitMQ` 并补齐启动校验、健康检查、失败闭环。
- “新增或修改测试”依赖 Phase 1 至 Phase 3 的源码改动完成。
- “真实测试”依赖测试代码与 RabbitMQ/PostgreSQL/Redis 测试环境准备完成。
- “回归修复”依赖真实测试结果。
- “文档回归”依赖最终源码、最终契约与最终测试结果。

## 文件层次图
```text
compose.yml                                      # 修改：增加 rabbitmq 服务与健康检查
config/
  modules/
    task_module/
      task_module_base.toml                      # 修改：任务注册清单与默认任务策略
      task_module_test.toml                      # 修改：测试任务注册清单
  runtime/
    message_runtime/
      message_runtime_base.toml                  # 修改：RabbitMQ 连接与交换机默认项
      message_runtime_test.toml                  # 新增：RabbitMQ 测试连接配置
    task_runtime/
      task_runtime_base.toml                     # 修改：任务后端公共配置与 funboost 扩展配置
      task_runtime_test.toml                     # 修改：测试环境任务后端配置
src/
  core/
    task_contract/
      message_bus_contract.py                    # 修改：补齐消息边界与兼容字段
      task_dispatcher_contract.py                # 修改：补齐分发结果字段
      task_handler_contract.py                   # 修改：明确处理器绑定契约
      task_registration_contract.py              # 新增：任务注册公共头 + 扩展体
      task_runtime_contract.py                   # 新增：任务运行时公共头 + 扩展体
  infrastructure/
    settings/
      app_settings_loader.py                     # 修改：加载任务注册与任务运行时判别联合配置
    task/
      task_registration_registry.py              # 新增：任务注册表与冲突校验
      funboost_task_dispatcher.py                # 新增：funboost 任务派发器
      funboost_task_bootstrapper.py              # 新增：funboost 任务装配器
      failed_task_recorder.py                    # 修改：失败记录与结构化日志承载
      rabbitmq_message_gateway.py                # 修改：连接配置校验与健康探测
      local_task_dispatcher.py                   # 修改：兼容注册中心与本地回退
      task_worker_supervisor.py                  # 修改：从字符串字典升级为绑定解析
    shared_resource_mount.py                     # 修改：统一任务基建初始化与关闭
test/
  contract_test/
    test_task_registration_contract.py           # 新增：注册契约与运行时契约测试
  unit_test/
    test_task_registration_registry_unit.py      # 新增：注册表解析与冲突测试
    test_funboost_task_dispatcher_unit.py        # 新增：funboost 派发器测试
    test_rabbitmq_message_gateway_unit.py        # 新增：RabbitMQ 配置校验与健康探测测试
  path_test/
    test_task_runtime_path.py                    # 新增：backend 选择与装配路径测试
  boundary_test/
    test_runtime_boundary.py                     # 修改：重试、重复注册、队列边界测试
  initialization_test/
    test_task_runtime_initialization.py          # 新增：启动装配与健康检查测试
  exception_test/
    test_runtime_exception.py                    # 修改：funboost 异常与失败记录回归
  integration_test/
    test_funboost_rabbitmq_integration.py        # 新增：真实 RabbitMQ 集成测试
    test_app_integration.py                      # 修改：应用层任务分发闭环回归
  convention_usage_test/
    test_end_to_end_usage.py                     # 修改：任务注册与派发用法回归
docs/
  design_docs/
    FastAPI统一Web基础设施实现规格.md          # 修改：回写真实任务基建现状
  2026_5_19_1818_funboost_rabbitmq任务队列基建完善执行方案.md  # 新增：本执行方案
```

## Phase 1
### 目标
先收口任务注册契约、任务运行时契约和配置模型，解决当前“只有 `default_job_kind`、`default_retry_limit`、`funboost_queue_name`，没有任务注册清单、没有每任务独立配置、没有强类型扩展体”的直接问题。

当前阶段完成后的中间结果是：配置层与契约层可以准确表达“注册了哪些任务、每个任务走哪个后端、每个任务的队列/路由/重试/并发参数是什么”，并在加载阶段就能做一致性校验。

### 依赖
- 依赖当前源码中的 `src/core/task_contract`、`config/modules/task_module/*`、`config/runtime/task_runtime/*`、`config/runtime/message_runtime/*`。
- 依赖当前 `app_settings_loader.py` 已有的判别联合实现方式；现有 `logging_contract` 的建模方式可直接复用。
- 依赖当前源码事实：`LocalTaskDispatcher` 已落地，`RabbitMqMessageGateway` 目前只做 URL 校验，历史文档中的“funboost 已接入”描述已过期。

### 模拟用法
```toml
[module]
default_retry_limit = 2
default_job_kind = "demo_task"

[[module.registrations]]
[module.registrations.header]
task_name = "demo_task"
job_kind = "demo_task"
enabled = true
backend = "funboost"
schema_version = "1.0"

[module.registrations.detail]
kind = "funboost"
schema_version = "1.0"
queue_name = "demo_task_queue"
exchange_name = "task.direct"
routing_key = "demo.task"
broker_kind = "RABBITMQ_AMQPSTORM"
retry_limit = 3
consumer_worker_count = 2
prefetch_count = 10
dead_letter_exchange = "task.dlx"
```

### 契约
| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| TaskRegistrationEnvelope | 任务注册信封 | 使用 `header + detail` 结构表达单个任务注册项，并校验 `header.backend` 与 `detail.kind`、`schema_version` 一致。 |
| TaskRegistrationHeader | 任务注册公共头 | 包含 `task_name`、`job_kind`、`enabled`、`backend`、`schema_version`，用于统一索引、启停控制与启动期校验。 |
| TaskRegistrationDetailUnion | 任务注册扩展体判别联合 | 仅允许强类型扩展体，所有扩展体必须带 `kind`、`schema_version` 且 `extra="forbid"`。 |
| LocalTaskRegistrationDetail | 本地任务扩展配置 | 表达 `kind="local"` 的本地执行配置，用于兼容当前单进程本地链路与测试回退。 |
| FunboostTaskRegistrationDetail | Funboost 任务扩展配置 | 表达 `kind="funboost"` 的任务级 RabbitMQ/funboost 配置，如 `queue_name`、`broker_kind`、`exchange_name`、`routing_key`、`retry_limit`、`consumer_worker_count`、`prefetch_count`。 |
| TaskRuntimeSettings | 任务运行时公共配置 | 扩展当前 `runtime.task`，从单薄字段升级为“公共字段 + 后端扩展字段”，承载 `backend`、`worker_enabled` 与 `backend_detail`。 |
| FunboostTaskBackendDetail | Funboost 运行时扩展配置 | 表达 `runtime.task.backend = "funboost"` 时的全局默认项，如默认 broker、发布确认、连接探测、启动校验与消费者默认参数。 |

### 任务清单
- [x] 新增 `src/core/task_contract/task_registration_contract.py`，定义任务注册公共头、扩展体判别联合与一致性校验。
- [x] 新增 `src/core/task_contract/task_runtime_contract.py`，定义任务运行时公共配置与 funboost 扩展配置。
- [x] 修改 `src/infrastructure/settings/app_settings_loader.py`，让 `TaskModuleSettings` 支持任务注册清单，让 `TaskRuntimeSettings` 支持 `backend_detail` 判别联合。
- [x] 修改 `config/modules/task_module/task_module_base.toml` 与测试配置，落地任务注册清单示例，而不是只有默认任务名。
- [x] 修改 `config/runtime/task_runtime/*.toml` 与 `message_runtime/*.toml`，收口 funboost 与 RabbitMQ 的全局运行时字段。
- [x] 增加启动期校验规则：重复 `job_kind`、重复队列、未知 `broker_kind`、外层后端与内层 `kind` 不一致时直接失败。
- [x] 保留现有本地默认值与测试友好性，避免第一阶段就破坏 `local` 后端与现有用例。

### 关键代码片段
```python
TaskRegistrationDetailUnion = Annotated[
    LocalTaskRegistrationDetail | FunboostTaskRegistrationDetail,
    Field(discriminator="kind"),
]


class TaskRegistrationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: TaskRegistrationHeader
    detail: TaskRegistrationDetailUnion
```

### 校验
- 配置加载阶段可以识别合法与非法的任务注册清单。
- `header.backend` 与 `detail.kind`、`schema_version` 不一致时会直接失败。
- 未知扩展字段、未知 `broker_kind`、重复 `job_kind`、重复队列名都能在轻量校验阶段被发现。

## Phase 2
### 目标
在稳定契约之上建立统一任务注册中心与装配链路，解决当前“`TaskWorkerSupervisor` 只是字符串到处理器的字典、`SharedResourceMount.register_task_handler` 无注册语义、`DispatchBackgroundJobUsecase` 不解析任务定义”的直接问题。

当前阶段完成后的中间结果是：任务派发不再只依赖裸 `job_kind` 字符串，而是先解析注册中心，再根据注册项选择本地或 funboost 路径，并能保持旧接口兼容。

### 依赖
- 依赖 Phase 1 的 `TaskRegistrationEnvelope`、`TaskRuntimeSettings` 与加载后的配置对象。
- 依赖当前 `DispatchBackgroundJobUsecase`、`TaskWorkerSupervisor`、`LocalTaskDispatcher`、`SharedResourceMount` 调用链。
- 依赖当前已有 `TaskMessageEnvelope` 与 `TaskDispatchResultPayload`，但允许在不破坏调用方的前提下补齐稳定字段。

### 模拟用法
```python
resource_mount.register_task_binding(
    RegisteredTaskBinding(
        job_kind="demo_task",
        payload_model=DemoTaskPayload,
        handler=DemoTaskHandler(),
    )
)
```

### 契约
| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| RegisteredTaskBinding | 已注册任务绑定 | 聚合 `job_kind`、`payload_model`、`handler` 与已加载任务注册项，作为运行时最小装配单元。 |
| TaskRegistrationRegistry | 任务注册表 | 负责注册项去重、启用态过滤、按 `job_kind` 解析、按 backend 分组与按队列索引。 |
| TaskDispatchDescriptor | 任务派发描述 | 在用例层统一收口 `job_kind`、`payload_kind`、`payload_json`、`deduplication_key`、`retry_limit`，避免派发路径散落拼装。 |
| TaskBootstrapSnapshot | 任务装配快照 | 记录实际装配成功、禁用、缺处理器、冲突失败的任务集合，供启动日志与健康检查使用。 |

### 任务清单
- [x] 新增 `src/infrastructure/task/task_registration_registry.py`，统一管理注册项、处理器绑定与冲突校验。
- [x] 修改 `src/infrastructure/task/task_worker_supervisor.py`，从简单 `dict[str, TaskHandler]` 升级为面向绑定对象的解析器。
- [x] 修改 `src/infrastructure/shared_resource_mount.py`，增加“加载注册清单 -> 绑定处理器 -> 生成任务装配快照 -> 选择 dispatcher”的装配流程。
- [x] 修改 `src/application/dispatch_background_job_usecase.py`，派发前先解析注册项，统一使用注册项中的任务级配置，而不是直接依赖全局默认值。
- [x] 修改 `src/core/task_contract/task_dispatcher_contract.py`，为分发结果补齐稳定结果字段，如 `backend`、`queue_name`、`published`。
- [x] 修改 `src/core/task_contract/task_handler_contract.py`，明确处理器入参与 payload 模型边界，避免无类型约束的隐式解析。
- [x] 保留 `register_task_handler(job_kind, handler)` 兼容包装层，但真实实现内部统一下沉到 `register_task_binding(...)`。
- [x] 新增 `TaskDispatchDescriptor`，在用例层统一收口 `job_kind`、`payload_kind`、`payload_json`、`deduplication_key`、`retry_limit`。

### 关键代码片段
```python
registration = task_registration_registry.get_enabled_registration(job_kind)

if settings.runtime.task.backend == TaskBackend.FUNBOOST:
    dispatcher = FunboostTaskDispatcher(...)
else:
    dispatcher = LocalTaskDispatcher(...)
```

### 校验
- 同一 `job_kind` 能解析到唯一注册项与唯一处理器绑定。
- 禁用任务不能被正常派发。
- 未注册任务、未绑定处理器、绑定模型与注册项不一致时，装配或派发阶段会明确失败。
- `local` 后端在引入注册中心后仍能通过现有本地链路工作。

## Phase 3
### 目标
完成 `funboost + RabbitMQ` 真实后端接入与稳健性补强，解决当前“RabbitMQ 只有 URL 校验、funboost 只有预留位、没有真实 broker 测试、没有健康检查、没有失败闭环”的直接问题。

当前阶段完成后的中间结果是：工程可以在真实 RabbitMQ 环境中完成任务发布、消费、重试、失败记录与关闭释放；`local` 路径继续保留为回退与测试路径。

### 依赖
- 依赖 Phase 1 与 Phase 2 形成的注册中心、配置契约与统一派发入口。
- 依赖本地环境已有 `funboost` 与 `amqpstorm` 包；若文档推荐与实际依赖不一致，以当前可运行依赖为准。
- 依赖 `compose.yml` 增加 RabbitMQ 服务后再做真实集成验证。

### 契约
| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| FunboostTaskDispatcher | Funboost 任务派发器 | 基于注册项把任务发布到 funboost/RabbitMQ，对外仍实现统一 `TaskDispatcher` 契约。 |
| TaskDispatchResultPayload | 任务分发结果 | 在现有结果上补齐 `backend`、`queue_name`、`published`、`worker_enabled` 等稳定字段，保证调用方可诊断。 |
| RabbitMqRuntimeHealth | RabbitMQ 运行时健康快照 | 表达 RabbitMQ 启动探测、连接可达性与失败原因，供 `SharedResourceMount` 状态与文档回归使用。 |
| TaskFailureRecordV2 | 失败任务记录 | 扩展当前失败记录，补齐 `backend`、`queue_name`、`retry_count`、`last_error`，覆盖 funboost 失败场景。 |

### 任务清单
- [x] 新增 `src/infrastructure/task/funboost_task_dispatcher.py`，实现真实 funboost 发布路径。
- [x] 新增 `src/infrastructure/task/funboost_task_bootstrapper.py`，负责根据注册清单装配 publisher、consumer 与处理器绑定。
- [x] 修改 `src/infrastructure/task/rabbitmq_message_gateway.py`，从单纯 URL 校验升级为连接参数校验、启动探测与健康快照输出。
- [x] 修改 `src/infrastructure/task/local_task_dispatcher.py`，让本地后端也基于注册中心工作，避免形成两套配置语义。
- [x] 修改 `src/infrastructure/shared_resource_mount.py`，在启动阶段根据 `runtime.task.backend` 初始化 `local` 或 `funboost`，并在关闭阶段执行资源释放。
- [x] 修改 `compose.yml`，增加 RabbitMQ 服务、健康检查与测试环境端口。
- [x] 修改 `src/infrastructure/task/failed_task_recorder.py`，补齐失败记录扩展字段与结构化日志承载。
- [x] 补齐失败闭环：funboost 发布失败、RabbitMQ 不可用、消费失败超重试上限时，统一落入失败记录与结构化日志。

### 关键代码片段
```python
if settings.runtime.task.backend == TaskBackend.FUNBOOST:
    rabbitmq_gateway.assert_available()
    self._task_dispatcher = FunboostTaskDispatcher(
        registration_registry=task_registration_registry,
        failed_task_recorder=self._failed_task_recorder,
    )
```

### 校验
- 启动时能识别 RabbitMQ 可达与不可达两种状态。
- `funboost` 后端能基于真实注册项把任务发布到指定队列。
- 任务执行失败时重试次数、失败记录与结果返回一致。
- 关闭应用时能正确释放 funboost/RabbitMQ 相关资源，不遗留悬挂连接。

## 新增或修改测试
本次测试目标是覆盖“任务注册契约 + 注册中心装配 + local/funboost 双后端 + RabbitMQ 真实链路 + 失败回归”。

- [x] 新增 `test/contract_test/test_task_registration_contract.py`，覆盖任务注册信封、外层与内层一致性校验、`extra="forbid"`。
- [x] 新增 `test/unit_test/test_task_registration_registry_unit.py`，覆盖重复注册、处理器绑定、未绑定处理器、注册项解析。
- [x] 新增 `test/unit_test/test_funboost_task_dispatcher_unit.py`，覆盖 funboost 派发器发布结果、错误收口与资源释放。
- [x] 新增 `test/unit_test/test_rabbitmq_message_gateway_unit.py`，覆盖 RabbitMQ 配置校验、连接探测与健康快照。
- [x] 新增 `test/path_test/test_task_runtime_path.py`，覆盖 `local`/`funboost` backend 切换路径。
- [x] 修改 `test/boundary_test/test_runtime_boundary.py`，覆盖 `retry_limit=0`、重复注册、队列边界配置。
- [x] 新增 `test/initialization_test/test_task_runtime_initialization.py`，覆盖 `SharedResourceMount` 在 `local` 与 `funboost` 两种模式下的装配与健康状态。
- [x] 修改 `test/exception_test/test_runtime_exception.py`，覆盖本地任务失败记录、funboost 配置异常回归。
- [x] 新增 `test/integration_test/test_funboost_rabbitmq_integration.py`，覆盖 RabbitMQ 探活与 funboost 派发结果回归。
- [x] 修改 `test/integration_test/test_app_integration.py` 与 `test/convention_usage_test/test_end_to_end_usage.py`，覆盖应用层调用方式与注册机制回归。

## 真实测试
1. `python -m compileall src test`
通过标准：受影响源码与测试文件全部可编译，无语法错误与导入错误。

2. `docker compose up -d postgres redis rabbitmq`
通过标准：在具备 Docker daemon 权限的宿主机/CI 上，PostgreSQL、Redis、RabbitMQ 全部健康，任务基建真实依赖具备可用测试环境。

3. `python -m pytest test/contract_test/test_task_registration_contract.py test/unit_test/test_task_registration_registry_unit.py test/unit_test/test_funboost_task_dispatcher_unit.py test/unit_test/test_rabbitmq_message_gateway_unit.py -q`
通过标准：任务注册契约、注册表、funboost 派发器与 RabbitMQ 网关单测全部通过。

4. `python -m pytest test/path_test/test_task_runtime_path.py test/boundary_test/test_runtime_boundary.py test/initialization_test/test_task_runtime_initialization.py test/exception_test/test_runtime_exception.py -q`
通过标准：任务装配路径、边界路径、初始化路径、异常路径全部通过。

5. `python -m pytest test/integration_test/test_funboost_rabbitmq_integration.py test/integration_test/test_app_integration.py test/convention_usage_test/test_end_to_end_usage.py -q`
通过标准：真实 RabbitMQ 集成、应用层任务派发闭环、用法规约回归全部通过。

6. `python -m pytest -q`
通过标准：全量测试通过，仅以退出码与断言失败判定；funboost 退出期日志噪声不计为失败。

实际执行时使用项目 `.venv` 解释器，裸 `python -m pytest` 是否可用取决于宿主环境。

## 回归修复
真实测试失败后，先修源码与配置，再修测试，最后修文档；不允许为了通过旧断言而回退正确实现。

- [x] 先判定失败归属：契约、配置、装配、真实 RabbitMQ 环境、funboost 适配、测试断言，避免混修。
- [x] 若失败来自源码实现，优先做最小必要修复，不混入与任务基建无关的重构。
- [ ] 若失败来自配置或环境，先修 `compose.yml`、测试配置与启动探测，再回跑最小失败集。
- [x] 若失败来自测试断言过期，按最终源码语义修正测试，而不是把实现退回到历史占位状态。
- [x] 每次修复后先回跑最小失败用例，再回跑对应分组，最后回跑 `python -m pytest -q`。
- [x] 若 RabbitMQ 集成失败，修复完成后必须重新回跑 `test_funboost_rabbitmq_integration.py` 与应用层集成测试。
- [ ] 若测试通过但退出期仍出现资源释放异常或日志噪声，必须修复后回跑 `test/unit_test/test_funboost_task_dispatcher_unit.py`、`test/initialization_test/test_task_runtime_initialization.py` 与 `python -m pytest -q`。

## 文档回归
需要把任务基建相关设计文档、配置说明、测试入口与最终源码保持一致，并明确指出历史文档中的过期描述。

- [x] 回写 `docs/design_docs/FastAPI统一Web基础设施实现规格.md` 的任务队列章节，明确当前真实形态是“local 回退 + funboost/rabbitmq 生产路径”。
- [x] 回写 `config/modules/task_module/*.toml`、`config/runtime/task_runtime/*.toml`、`config/runtime/message_runtime/*.toml` 的字段说明与示例。
- [x] 若历史方案仍写着“funboost 仅预留位”或“RabbitMQ 只做校验”，在相关文档处标注历史内容可能过期，以源码为准。
- [x] 同步测试入口、真实依赖准备方式、回归命令顺序，确保后续执行人可以直接复跑。
- [x] 复核本执行方案与最终源码、最终测试结果一致，避免把计划态内容当成既成事实写回文档。
