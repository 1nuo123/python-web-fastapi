# 运维检查清单

## 1. 文档目的
提供上线和排障前检查项。

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
- `app` 必须保持 `User=app`、只读根文件系统、`cap_drop=ALL`、`no-new-privileges`、`PidsLimit=256`、1 GiB/2 CPU 上限和 `/tmp` 临时写边界。
- RabbitMQ 健康检查必须使用 `check_port_connectivity`；镜像必须包含 `funboost_config.py`、`nb_log_config.py`，生产日志入口必须指向 `/tmp/logs`。
- 生产任务拓扑已显式拆分：`app` 负责 Funboost producer-only 发布，`task-worker` profile 负责消费；两者使用相同 RabbitMQ 可靠拓扑和任务注册。

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
- 如果 Redis 运行期不可用，限流链路应返回统一 503 而不是 500；恢复 Redis 后 `/health/ready` 应重新返回 200。
- 上线前检查 `docker compose -f compose.yml -f compose.production.yml config` 输出中 PostgreSQL、Redis、RabbitMQ 没有宿主机 `ports`，并确认 `app`、`migration` 容器环境含有生产连接串而不是示例占位值。
- 本地 RabbitMQ 端口被占用或被系统策略拒绝时，先改用 `RABBITMQ_AMQP_HOST_PORT=55672` 与 `RABBITMQ_MANAGEMENT_HOST_PORT=15673` 重启 compose，再用同步后的 `RABBITMQ_TEST_URL` 执行 RabbitMQ 集成测试。
- 如果生产启动报 “producer-only”，检查 `config/runtime/task_runtime/task_runtime_production.toml`、`config/modules/task_module/task_module_production.toml` 与部署注入的任务后端覆盖策略，确认默认任务类型在当前后端存在启用声明。
- 上线任务消费前使用 `--profile task-worker` 解析并启动叠加配置，确认 worker 健康；如果本地 `.env` 使用弱密钥导致 production fail closed，应注入正式密钥，不得降低安全校验。

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
