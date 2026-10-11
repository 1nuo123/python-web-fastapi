# 生产部署

当前服务器从私有仓库拉取代码开始的一键部署、备份、恢复、回滚、安全和日常运维命令，以
[生产环境 Docker 一键部署与长期运维指南](../../生产环境Docker一键部署与长期运维指南.md)
为准。本页保留配置模型和代码结构说明，不再作为生产命令的单一入口。

## 1. 文档目的
说明 production 覆盖、安全要求和运维注意事项。

**最后更新范围**：覆盖 `config`、`.env*.example`、Dockerfile、Compose 和 CLI；不读取或写入真实 `.env` 值。

## 2. 适用读者
- 后端开发者
- 运维部署人员
- 安全审查人员

## 3. 关联源码
| 路径 | 作用 |
| --- | --- |
| `config/app_base.toml` | 基础配置。 |
| `config/runtime` | 运行时配置。 |
| `config/modules` | 模块配置。 |
| `src/infrastructure/settings/app_settings_loader.py` | 配置加载。 |
| `Dockerfile` | 镜像入口。 |
| `compose.yml` | 本地编排。 |
| `compose.production.yml` | 生产覆盖。 |
| `.github/workflows/production-image.yml` | 在 CI 构建并推送后端生产镜像。 |
| `typescript-web-nuxt/.github/workflows/production-image.yml` | 在 CI 构建并推送前端生产镜像。 |
| `deploy/production.sh` | 检查 CI 镜像、备份并驱动生产发布。 |
| `deploy/run-production-ip.sh` | 拉取 Digest 镜像、迁移并启动生产 Compose。 |
| `config/runtime/message_runtime/message_runtime_production.toml` | 生产消息后端覆盖为 RabbitMQ。 |
| `config/runtime/task_runtime/task_runtime_production.toml` | 生产任务后端覆盖为 Funboost，供 Web 发布节点和独立 worker 共用。 |
| `config/modules/task_module/task_module_production.toml` | 生产任务模块启用 `task_execution_probe` 注册。 |
| `src/infrastructure/resource_mount/runtime_resource_bootstrapper.py` | 启动期校验任务后端与消息后端组合。 |

## 4. 核心结论
- `APP_ENV` 选择 development/test/production。
- 生产环境禁用 `.env` 读取；容器进程最终必须具备 `DATABASE_URL`、带密码的 `REDIS_URL`、带账号密码的 `RABBITMQ_URL`、不少于 32 字符且非示例值的 `JWT_SECRET`。`compose.production.yml` 通过 `POSTGRES_*`、`REDIS_PASSWORD`、`RABBITMQ_*` 拼装前三个连接串。
- `compose.yml` 本地暴露 PostgreSQL、Redis、RabbitMQ；`compose.production.yml` 使用 `ports: !reset []` 收紧 PostgreSQL、Redis、RabbitMQ 端口，应用端口仍由 `APP_HOST_PORT` 控制。
- Dockerfile healthcheck 会根据 `runtime.web.api_prefix` 拼接探活路径；默认检查严格就绪端点 `/health/ready`。
- 生产 app 使用非 root `app` 用户、只读根文件系统、`cap_drop=ALL`、`no-new-privileges`、256 PIDs、1 GiB 和 2 CPU 上限；可写边界限定为 tmpfs `/tmp`，第三方日志入口使用 `/tmp/logs`。
- 生产 migration、app 和 task-worker 使用同一个由 CI 构建的后端镜像；生产前端使用由 CI 构建的前端镜像。生产服务器不执行项目镜像构建。
- 镜像显式携带 `funboost_config.py` 与 `nb_log_config.py`，避免第三方库在只读虚拟环境中自动生成配置；RabbitMQ 健康检查使用 `check_port_connectivity` 等待 AMQP 监听就绪。
- 生产任务拓扑已显式拆分：`app` 是 Funboost producer-only 节点，`task-worker` profile 运行 `src.cli.run_task_worker` 消费 RabbitMQ；两者共享可靠发布拓扑和 `task_execution_probe` 注册。

## 5. 结构说明
配置加载先由 `APP_ENV` 选择 environment 层级并合并 TOML，再应用非 production dotenv 和进程环境变量覆盖；部署入口通过 Compose 注入服务地址和密钥。

生产 Compose 启动必须同时加载 `compose.yml` 和 `compose.production.yml`，并通过 `--env-file <production-env-file>`、进程环境、Compose Secret 或外部 Secret Manager 提供真实值。`compose.production.yml` 会把 `APP_ENV` 固定为 `production`，并为 `app`、`migration` 容器注入 `DATABASE_URL`、`REDIS_URL`、`RABBITMQ_URL`、`JWT_SECRET`。

## 6. 工作流程
```mermaid
flowchart TD
    A["config/*.toml"] --> B["AppSettingsLoader"]
    C["process env"] --> B
    D[".env non-production only"] --> B
    B --> E["ApplicationSettings"]
    E --> F["FastApiAppAssembler"]
```

## 7. 关键实现
| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `AppSettingsLoader._apply_dotenv_overrides` | `src/infrastructure/settings/app_settings_loader.py` | 应用环境变量覆盖。 |
| `SettingsSecurityValidator` | `src/infrastructure/settings/settings_security_validator.py` | 生产安全校验。 |
| `DatabaseMigrationCli` | `src/cli/run_database_migrations.py` | 部署迁移入口。 |

## 8. 如何修改或扩展
1. 新增配置时更新 base 和必要的 environment 覆盖。
2. 如为敏感项，添加环境变量覆盖并更新 example 文件。
3. 更新配置文档、运维清单和测试。

## 9. 测试覆盖
| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_dotenv_settings_loader_unit.py` | dotenv 加载。 |
| initialization | `test/initialization_test/test_runtime_initialization.py` | 初始化。 |
| integration | `test/integration_test/test_security_production_integration.py` | 生产安全配置。 |
| integration | `test/integration_test/test_migration_job_integration.py` | 迁移门禁、Dockerfile 入口配置和健康检查。 |

## 10. 常见问题
- 如果 production 启动失败，多数情况是必需环境变量缺失或密钥弱。
- 如果日志出现只读文件系统错误，确认最终镜像包含两个第三方入口配置，并且 `LOGGING_ENTRY_LOG_PATH=/tmp/logs`。
- 如果应用在 RabbitMQ 容器健康后仍短暂连接失败，确认健康命令是 `rabbitmq-diagnostics -q check_port_connectivity`，不是仅检查节点进程的 `ping`。
- 如果错误信息包含 “producer-only”，检查 `config/runtime/task_runtime/task_runtime_production.toml`、`config/modules/task_module/task_module_production.toml` 与部署注入的任务后端覆盖策略，确认默认任务类型在当前后端存在启用声明。

## 11. 维护备注
配置/部署变更时同步检查 Docker 指南、环境变量文档和故障排查。

### 环境变量索引

| 变量名 | 用途 | 示例格式 |
| --- | --- | --- |
| `APP_ENV` | 选择配置环境。 | `development` / `test` / `production` |
| `DATABASE_URL` | 数据库连接串。 | `postgresql+psycopg://user:password@host:5432/db` |
| `REDIS_URL` | Redis 连接串；生产必须包含密码。 | `redis://:password@redis:6379/0` |
| `RABBITMQ_URL` | RabbitMQ 连接串；生产必须包含专用账号和密码，禁止 `guest/guest`。 | `amqp://user:password@rabbitmq:5672/%2F` |
| `JWT_SECRET` | JWT 密钥；生产至少 32 字符且不能使用示例/本地片段。 | 至少 32 字符的随机字符串 |
| `AUTH_BOOTSTRAP_ADMIN_PASSWORD` | 引导管理员密码覆盖；生产长期运行应为空或不启用 bootstrap admin。 | `<secret-or-empty>` |
| `RUNTIME_WEB_API_PREFIX` | 覆盖 API 前缀。 | `/api` |
| `INITIAL_ADMIN_USERNAME` | 初始管理员 CLI 用户名。 | `admin` |
| `INITIAL_ADMIN_PASSWORD` | 初始管理员 CLI 密码；禁止写入日志或文档示例真实值。 | `<secret>` |
| `INITIAL_ADMIN_SUBJECT_ID` | 初始管理员主体 ID；为空时由仓储生成。 | `<uuid-or-id>` |
| `INITIAL_ADMIN_CONFIRM` | 初始管理员 CLI 静态确认短语。 | `create-initial-admin` |
| `INITIAL_ADMIN_ALLOW_PRODUCTION` | 生产环境显式允许执行初始管理员 CLI。 | `true` |
| `INITIAL_ADMIN_DATABASE_FINGERPRINT` | 生产目标库指纹，按当前 DSN 与 schema 计算后匹配。 | `<sha256-hex>` |
| `INITIAL_ADMIN_BOOTSTRAP_SECRET` | 生产一次性 bootstrap secret。 | `<one-time-secret>` |
| `INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM` | 生产一次性 bootstrap secret 二次确认；校验成功后从进程环境消费清除。 | `<one-time-secret>` |

## 12. 相关文档
- [项目文档总览](../README.md)
- [快速启动](../00_project_overview/quick_start.md)
- [Docker 启动运行指南](../../Docker启动运行指南.md)
