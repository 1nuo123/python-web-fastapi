# 环境变量

## 1. 文档目的
说明配置加载器和 Compose 使用的环境变量，不泄露真实 `.env` 值。

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

## 4. 核心结论
- `APP_ENV` 选择 development/test/production。
- 生产环境禁用 `.env` 读取；容器进程最终必须具备 `DATABASE_URL`、带密码的 `REDIS_URL`、带账号密码的 `RABBITMQ_URL`、不少于 32 字符且非示例值的 `JWT_SECRET`。`compose.production.yml` 通过 `POSTGRES_*`、`REDIS_PASSWORD`、`RABBITMQ_*` 拼装前三个连接串。
- `compose.yml` 本地暴露 PostgreSQL、Redis、RabbitMQ；`compose.production.yml` 使用 `ports: !reset []` 收紧 PostgreSQL、Redis、RabbitMQ 端口，应用端口仍由 `APP_HOST_PORT` 控制。
- Dockerfile healthcheck 会根据 `runtime.web.api_prefix` 拼接探活路径；默认检查严格就绪端点 `/health/ready`。
- 初始管理员生产 CLI 除基础输入外，还必须提供生产显式开关、目标库指纹和一次性 bootstrap secret；secret 校验成功后会从进程环境消费清除。

## 5. 结构说明
配置加载先由 `APP_ENV` 选择 environment 层级并合并 TOML，再应用非 production dotenv 和进程环境变量覆盖；部署入口通过 Compose 注入服务地址和密钥。

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

## 10. 常见问题
- 如果 production 启动失败，多数情况是必需环境变量缺失或密钥弱。

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

### Compose 变量补充

| 变量名 | 用途 | 备注 |
| --- | --- | --- |
| `APP_HOST_PORT` | app 服务宿主机端口。 | 映射到容器 `8000`；生产覆盖不会移除 app 端口。 |
| `POSTGRES_DB/USER/PASSWORD` | PostgreSQL 初始化与连接串拼装。 | `POSTGRES_PASSWORD` 不应使用示例值。 |
| `POSTGRES_HOST_PORT` | 本地 PostgreSQL 宿主机端口。 | 生产覆盖会重置 PostgreSQL `ports`。 |
| `REDIS_PASSWORD` | 生产 Redis 密码。 | `compose.production.yml` 用它拼装 `REDIS_URL`；本地基础 compose 不启用 Redis 密码。 |
| `REDIS_HOST_PORT` | 本地 Redis 宿主机端口。 | 生产覆盖会重置 Redis `ports`。 |
| `RABBITMQ_DEFAULT_USER/PASS/VHOST` | RabbitMQ 初始化账号和 vhost。 | 生产必须提供专用账号密码。 |
| `RABBITMQ_VHOST_ENCODED` | Compose 拼接 `RABBITMQ_URL` 使用的 URL 编码 vhost。 | 默认 `%2F`。 |
| `RABBITMQ_AMQP_HOST_PORT/MANAGEMENT_HOST_PORT` | 本地 RabbitMQ AMQP 与管理台端口。 | 生产覆盖会重置 RabbitMQ `ports`。 |

## 12. 相关文档
- [项目文档总览](../README.md)
- [快速启动](../00_project_overview/quick_start.md)
- [Docker 启动运行指南](../../Docker启动运行指南.md)
