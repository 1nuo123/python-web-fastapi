# 依赖方向

## 1. 这是什么

定义项目内**允许的 import 方向**与**禁止的 import 方向**，区分 import-linter 实际强制的层级规则与组合根/薄路由等评审约定，并解释 core 的框架类型例外。评审发现可疑 import 时，用本文判定是静态规则违规还是设计约定偏离。

**最后更新范围**：覆盖 import-linter 四条契约、应用端口、`WebBundle`/`PersistenceSession` 例外、组合根豁免与测试 fake 的引用限制。

## 2. 规则总表

| 源层 | 可以依赖 | 禁止依赖 | 强制手段 |
| --- | --- | --- | --- |
| `src/core` | 标准库、pydantic、（例外）fastapi.APIRouter | api / application / domain / infrastructure | import-linter |
| `src/domain` | core | api / application / infrastructure | import-linter |
| `src/application` | core、domain、自身 ports | api / infrastructure | import-linter |
| `src/infrastructure` | core、domain、application、第三方库 | api | import-linter；“优先只依赖 application/ports”是设计方向，不是当前强制规则 |
| `src/api` | 所有层（其中 Web 主对象图集中在组合根） | —— | import-linter 无禁止项；薄路由与集中组装由评审/路径测试维护 |

要点：

- **infrastructure 可以 import application**。这不是违规——`SharedResourceMount` 要实现 `src/application/ports` 的 Protocol；当前 `resource_mount` 还引用 `AuthorizationGuard` 和安全管理用例类型，持久化映射也引用 admin identity command。被 import-linter 禁止的是反方向（application → infrastructure），不能把“基础设施只依赖 ports”误写成已强制事实。
- **api 是最外层**，理论上可以 import 一切；但为了保持路由薄适配，业务路由文件只应 import 自身 contract、`DependencyContextAccessor`、core 契约与 domain 授权常量，跨层组装集中在组合根。

## 3. 为什么这样设计

依赖方向的目标是**可替换性**与**编译期可发现性**：

1. 用例依赖 Protocol（结构化鸭子类型），测试可注入任意满足签名的 fake，不需要 mock 补丁。
2. infrastructure 换实现（Memory→Redis、Local→RabbitMQ）时，编译面只在装配器与配置模型，业务代码零改动。
3. import-linter 把违规变成 CI 失败而不是 code review 口头约定；`uv run nox -s static` 每次执行。

## 4. 两个 core 契约例外（详细边界）

### 4.1 `WebBundle`（core 持有 `fastapi.APIRouter`）

```36:48:src/core/http_contract/web_bundle_contract.py
@dataclass(slots=True)
class WebBundle:
    """
    Web集合数据对象，用于承载当前流程的结构化字段。
    ...
    """

    module_name: str
    router: APIRouter
```

允许的使用面：`src/api` 的 provider 产出它、`src/infrastructure/fastapi_route_composer.py` 消费它。**不允许**：业务用例、仓储、任何 core 业务契约接触 `APIRouter`。

### 4.2 `PersistenceSession`（名义会话协议）

`UnitOfWork.get_session()` 返回 `PersistenceSession`（core 中定义的空协议类）；`SqlAlchemyPersistenceSession`（infrastructure）同时继承 SQLAlchemy `Session` 与该协议。仓储工厂端口（如 `AuthRuntimePort.create_refresh_token_repository(session: PersistenceSession)`）以协议类型收参，具体仓储实现内部再收窄为 SQLAlchemy 会话。这样用例代码引用不到 SQLAlchemy 符号，而 infrastructure 拿到的是真实会话。

## 5. 组合根与最外层接线（不是 linter 豁免）

四条 forbidden 契约按**源包**判定，没有为具体文件设置豁免：`src/api` 本身是最外层，所以 `FastApiAppAssembler`、`DependencyContextAccessor`、`TestAppFactory` 可以跨层接线；`AsgiApplicationFactory` 当前只把调用参数转交给 assembler。Web 主对象构建应继续集中在 assembler，依赖读取集中在 accessor，测试替换集中在 test factory。新代码是否适合进入这些位置，应看它是否只做“构造、连接、读取已装配依赖或测试替换”，而不是把业务规则搬进最外层。

## 6. 测试 fake 的引用限制

`src/infrastructure/testing`（`FakeCacheStore`、`FakeClock`、`FakeMessageBus`、`SqliteTestEngineFactory`、任务/缓存测试支撑）只允许被 `test/**` 与 `src/api/testing/test_app_factory.py` 引用。生产装配路径出现这些符号视为缺陷（评审 + `test/path_test` 约定测试保护）。

## 7. 常见违规与纠正

| 违规 | 症状 | 纠正 |
| --- | --- | --- |
| 用例 import 仓储实现 | application → infrastructure，static 检查失败 | 在 ports 定义仓储工厂方法，装配器注入 |
| 路由内直接 `create_engine`/`Redis()` | 资源生命周期失控 | 经 `DependencyContextAccessor` 读 `resource_mount` 提供的能力 |
| core 契约里 import ORM 模型 | core → infrastructure | 在 core 定义快照/载荷模型，仓储做 ORM↔契约映射 |
| 中间件 import 路由模块取常量 | infrastructure → api | 把常量下沉到 core 或 domain |
| 出现循环 import | 启动 ImportError | 通常是 route/usecase/infrastructure 互相穿透；用 `TYPE_CHECKING` 块只解决类型标注，运行期依赖必须重新分层 |

## 8. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| static | import-linter（`uv run nox -s static`） | 四条 forbidden 契约。 |
| unit | `test/unit_test/test_application_port_boundary_unit.py` | 端口边界。 |
| boundary | `test/boundary_test/test_hard_migration_module_boundary.py` | 模块/运行时边界。 |
| path | `test/path_test/test_runtime_path.py` | 运行时读取路径。 |

## 9. 相关文档

- [项目文档总览](../README.md)
- [分层架构](layered_architecture.md)
- [评审清单](../09_development_guide/review_checklist.md)
