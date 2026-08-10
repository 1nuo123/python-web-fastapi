# 持久化与迁移

## 1. 这是什么

从基础设施视角详解持久化栈：引擎工厂（连接池/超时/schema search_path）、会话工厂与工作单元、共享会话管理器，以及 Alembic 迁移的三个执行入口（启动自动升级、CLI、compose migration 服务）。表结构与仓储的细节在 [06_data](../06_data/database_overview.md) 专章。

**最后更新范围**：覆盖 `src/infrastructure/persistence/` 根级 7 个文件、`alembic/env.py`、`alembic_runner.py` 与 database_runtime 配置。

## 2. 组件与职责

| 组件 | 文件 | 关键行为 |
| --- | --- | --- |
| `SqlAlchemyEngineFactory` | `sqlalchemy_engine_factory.py` | `create_engine(url, pool_pre_ping=True, pool_size, max_overflow, pool_recycle, connect_args={connect_timeout, options="-csearch_path={schema}"})`；`validate()` 执行 `SELECT 1` 探活，失败抛 503 `system.database.unavailable`。 |
| `DatabaseEngineFactory`（Protocol） | `database_engine_factory_contract.py` | 引擎工厂契约；测试注入 `SqliteTestEngineFactory` 替换。 |
| `SqlAlchemyPersistenceSession` | `sqlalchemy_session_factory.py` | 同时继承 SQLAlchemy `Session` 与 core `PersistenceSession` 协议的名义会话。 |
| `SqlAlchemySessionFactory` | 同上 | `sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False, future=True)`；`read_checked_out_connections()` 供饱和度指标。 |
| `SqlAlchemyUnitOfWork` | 同上 | commit/flush/rollback/dispose 四操作包装（dispose=close 归还连接）。 |
| `SharedDbSessionManager` | `resource_slot/shared_db_session_manager.py` | 持有会话工厂，为 store/writer 等长生命周期组件按需创建 UoW。 |
| `AlembicRunner` | `alembic_runner.py` | 程序化 Alembic：注入 script_location/url/schema/connect_timeout 四选项后 `upgrade head`（无 alembic.ini 依赖）。 |
| `alembic/env.py` | `AlembicEnvironment` | online 模式先 `CREATE SCHEMA IF NOT EXISTS` 再迁移；NullPool；`include_schemas` + `version_table_schema` 钉在配置 schema；compare_type/server_default 开启（autogenerate 精度）。 |
| `sqlalchemy_metadata_registry.py` | `ORM_MODEL_METADATA` | 全部 ORM 模型共享的 metadata（env.py 的 autogenerate 目标）。 |

## 3. 设计要点

- **expire_on_commit=False**：commit 后快照对象仍可读（用例 commit 后还要把结果映射成响应），避免离开会话的懒加载爆炸；代价是提交后的对象是"当时值"，约定不复用跨事务实体。
- **schema 隔离**：连接层 `search_path` 与迁移层 `version_table_schema` 都钉在 `runtime.database.schema`（配置校验限定单个合法 PostgreSQL 标识符），同库多应用可按 schema 隔离；迁移前自动建 schema。
- **pool_pre_ping + pool_recycle**：借出前 ping 掉断连，定期回收长连接，抵御数据库端/中间件空闲断链。
- **引擎可注入**：`create_app(database_engine_factory=...)` 是离线测试用 SQLite 的钩子；生产不传即用默认工厂。

## 4. 迁移的三个入口

| 入口 | 场景 | 行为 |
| --- | --- | --- |
| 启动自动升级 | `runtime.database.auto_upgrade_on_startup=true`（开发/测试便利） | 数据库资源初始化时 `upgrade_head`；生产建议关闭，用独立迁移步骤 |
| CLI | `python -m src.cli.run_database_migrations` | 加载当前环境配置 → upgrade head → 输出强类型 `MigrationJobResult`，退出码 0/1 |
| compose `migration` 服务 | `docker compose up` 默认链路 | 一次性容器跑 CLI，`app` 服务 `depends_on: service_completed_successfully`——迁移失败应用不启动 |

迁移脚本位于 `src/infrastructure/persistence/alembic/versions/`（命名 `YYYYMMDDHHMM_描述.py`，当前 head `202608081000_add_codex_host_compatibility`）。完整版本谱系见 [Alembic 迁移](../06_data/alembic_migrations.md)。

## 5. 配置（runtime.database）

`backend=postgresql`（唯一支持）、`url`（生产由 DATABASE_URL 覆盖）、`schema`、`echo`、`pool_size`、`max_overflow`、`pool_recycle_seconds`、`connect_timeout_seconds`、`auto_upgrade_on_startup`。全部数值必须为正；连接池整块 restart_required。饱和度上限 `database_connection_limit` 由 `RuntimeCapacityPolicyResolver` 从 pool_size+max_overflow 解析，供 `runtime_saturation_ratio{resource="db_pool"}`。

## 6. 注意事项

- 事务纪律（用例内 commit/rollback/dispose 样板）见[事务边界](../06_data/transaction_boundary.md)；任何路径漏 `dispose()` 都会泄漏连接，池耗尽表现为请求 503/超时与 db_pool 饱和度逼近 1。
- Alembic 用独立 NullPool 引擎，不共享应用连接池——迁移期间的连接压力与应用池无关。
- 新迁移必须与 ORM 模型同步修改并跑 `compare_type` 精度下的 autogenerate 核对；流程见[新增迁移](../09_development_guide/adding_new_migration.md)。
- SQLite（测试）与 PostgreSQL 方言差异由 `database_dialect.py` 和仓储实现内的方言分支处理；写迁移时只考虑 PostgreSQL（迁移不在 SQLite 上执行，测试库由 metadata create_all 构建）。

## 7. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_sqlalchemy_session_factory_unit.py` | 会话/UoW 行为。 |
| initialization | `test/initialization_test/test_runtime_initialization.py` | 引擎探活与迁移开关。 |
| integration | `test/integration_test/test_database_migration_integration.py` | 真实 PostgreSQL 迁移执行。 |
| integration | `test/integration_test/test_app_integration.py` | migration→app 启动链。 |

## 8. 相关文档

- [项目文档总览](../README.md)
- [数据库总览](../06_data/database_overview.md)
- [Alembic 迁移](../06_data/alembic_migrations.md)
- [事务边界](../06_data/transaction_boundary.md)
- [新增迁移](../09_development_guide/adding_new_migration.md)
