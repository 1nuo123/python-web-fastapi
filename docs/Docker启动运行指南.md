# Docker 启动运行指南

## 1. 前置条件

- 已安装 Docker Desktop 或 Docker Engine。
- 使用支持 `docker compose` 的 Compose v2。
- 在项目根目录执行命令：`E:\python_web_fastapi\work`。

## 2. 本地开发首次启动

```powershell
cd E:\python_web_fastapi\work
Copy-Item .env.docker.example .env
docker compose up -d --build
```

首次启动会自动执行数据库迁移：`migration` 服务会先运行 `python -m src.cli.run_database_migrations`，成功后 `app` 才启动。

开发环境会创建引导管理员：

- 用户名：`admin`
- 密码：`.env` 中的 `AUTH_BOOTSTRAP_ADMIN_PASSWORD`

检查状态：

```powershell
docker compose ps
docker compose logs migration
docker compose logs -f app
```

访问地址：

- 存活检查：`http://127.0.0.1:8000/health/live`
- 严格就绪检查：`http://127.0.0.1:8000/health/ready`；Dockerfile 使用该端点。
- 就绪检查：`http://127.0.0.1:8000/health/ready`
- Swagger：`http://127.0.0.1:8000/docs`

## 3. 日常启停

```powershell
docker compose stop
docker compose start
docker compose down
```

彻底重置本地数据：

```powershell
docker compose down -v
docker compose up -d --build
```

`down -v` 会删除 PostgreSQL 数据卷，数据库会重新变成空库。

## 4. 修改代码后

当前 Compose 没有挂载源码目录，代码变更后需要重建镜像：

```powershell
docker compose up -d --build app
```

如果只想重启已有镜像：

```powershell
docker compose restart app
```

如果改了 `pyproject.toml` 或 `uv.lock`，也使用：

```powershell
docker compose up -d --build app
```

## 5. 修改数据库结构后

1. 在 `src\infrastructure\persistence\alembic\versions` 新增或修改 Alembic 迁移脚本。
2. 重建镜像并手动执行迁移：

```powershell
docker compose build app migration
docker compose run --rm migration
docker compose up -d --no-deps app
```

已有容器后，不要只依赖 `docker compose up -d` 触发迁移；后续库表变更请显式运行 `docker compose run --rm migration`。

## 6. 手动重跑迁移

```powershell
docker compose run --rm migration
```

迁移目标固定为 Alembic `head`，重复执行应保持幂等。

## 7. 修改配置或环境变量后

修改 `.env` 后重建并重启：

```powershell
docker compose up -d --build
```

常用变量：

- `APP_HOST_PORT`：宿主机访问端口，默认 `8000`
- `POSTGRES_HOST_PORT`：宿主机 PostgreSQL 端口，默认 `55432`
- `POSTGRES_DB`：开发数据库名，默认 `fastapi_web_skeleton_dev`
- `POSTGRES_PASSWORD`：本地开发 PostgreSQL 密码，默认样例为 `local-dev-postgres-password`
- `JWT_SECRET`：JWT 密钥
- `AUTH_BOOTSTRAP_ADMIN_PASSWORD`：开发环境引导管理员密码
- `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS`：本地 RabbitMQ 用户和密码，默认样例为 `fastapi_dev` / `local-dev-rabbitmq-password`

`config/.env.example` 已废弃，不再作为 dotenv 入口。开发与 Docker 环境只复制仓库根目录 `.env.docker.example`，生产环境只使用仓库根目录 `.env.production.example` 或外部注入的等效环境变量。

测试数据库默认由 `test/conftest.py` 从开发库名推导为 `<POSTGRES_DB>_test`，当前样例为 `fastapi_web_skeleton_dev_test`。本地测试默认连接 `127.0.0.1:55432`，密码与 `.env.docker.example` 保持一致。

## 8. 生产方式启动

```powershell
cd E:\python_web_fastapi\work
Copy-Item .env.production.example .env.production
# 编辑 .env.production，替换所有 replace_with_* 示例值
docker compose --env-file .env.production -f compose.yml -f compose.production.yml up -d --build
```

生产组合会关闭 PostgreSQL、Redis、RabbitMQ 的宿主机端口暴露，只保留应用端口；OpenAPI/Swagger 默认关闭。

生产环境必须使用真实强密钥和专用账号，不能使用示例密码、弱 `JWT_SECRET` 或 RabbitMQ `guest/guest`。

## 9. 登录验证

```powershell
$body = @{ username = "admin"; password = "你的引导管理员密码" } | ConvertTo-Json -Compress
Invoke-WebRequest -Method Post -Uri "http://127.0.0.1:8000/auth/token" -ContentType "application/json" -Body $body
```

如果 `RUNTIME_WEB_API_PREFIX` 被设置为非空前缀，所有接口地址前面都要加这个前缀。

## 10. 历史数据卷迁移

如果本机已经存在旧 `postgres_data` 数据卷，`docker compose up -d` 可能不会重新应用 `.env` 中的新 `POSTGRES_PASSWORD` 和 `POSTGRES_DB`。常见表现是 `migration` 服务报 `password authentication failed` 或 `fastapi_web_skeleton_dev does not exist`。

保留数据时可进入 PostgreSQL 容器手动对齐：

```powershell
docker exec fastapi-web-skeleton-postgres-1 psql -U postgres -d postgres -c "ALTER USER postgres WITH PASSWORD 'local-dev-postgres-password';"
docker exec fastapi-web-skeleton-postgres-1 psql -U postgres -d postgres -c "CREATE DATABASE fastapi_web_skeleton_dev;"
docker compose -f compose.yml up -d
```

若确认可以清空本地数据，可使用 `docker compose down -v` 删除数据卷后重新启动。

## 11. 当前回归结果

- `docker compose -f compose.yml up -d`：通过，`app`、`postgres`、`redis`、`rabbitmq` 均运行且健康。
- `$env:RABBITMQ_INTEGRATION_ENABLED='1'; .\.venv\Scripts\python.exe -m pytest -q`：通过，`630 passed, 62 warnings`。

## 12. 流式服务启动与优雅停机

容器入口固定为：

```text
python -m src.cli.run_web_server
```

该入口从 `runtime.stream` 读取并传给 Uvicorn：

- `websocket_max_message_bytes` → `ws_max_size`；
- `websocket_ping_interval_seconds` → `ws_ping_interval`；
- `websocket_ping_timeout_seconds` → `ws_ping_timeout`；
- `shutdown_grace_seconds + 5` → `timeout_graceful_shutdown`。

Dockerfile 使用 `STOPSIGNAL SIGTERM`。收到 SIGTERM 后，应用先撤销 readiness 并拒绝新流会话，再通知
现有会话、等待 `shutdown_grace_seconds`、取消剩余任务，最后关闭 Redis/内存状态存储和其他共享资源。
`compose.yml` 的 `stop_grace_period: 40s` 必须大于应用排空窗口与 Uvicorn 缓冲时间之和；修改生产
`shutdown_grace_seconds` 时必须同步检查编排平台 termination grace。

生产 Redis 流恢复依赖 `REDIS_URL`。`redis_stream_runtime` 启动时连接或探测失败会阻止 readiness；
单次票据消费同样 fail-closed。Compose 还为 app 设置 `pids_limit: 256` 与 `mem_limit: 1g`，避免长连接
任务失控扩散到宿主机。

代码、Dockerfile、依赖或流运行时配置变化后必须重建镜像，不能只执行无 `--build` 的 `up -d`：

```powershell
docker compose -f compose.yml up -d --build
docker compose -f compose.yml ps
docker compose -f compose.yml logs --no-color --tail 100 app
docker inspect fastapi-web-skeleton-app-1 --format '{{json .Config.Cmd}} {{json .State.Health.Status}}'
```

期望命令为 `["python","-m","src.cli.run_web_server"]`，健康状态为 `healthy`。

## 13. SSE 与 WebSocket 反向代理要求

SSE 路由必须关闭代理缓冲、缓存和响应转换，代理读超时必须大于 SSE 心跳间隔及允许的最长空闲时间。
应用已经返回 `Cache-Control: no-cache, no-transform` 和 `X-Accel-Buffering: no`，代理仍需显式遵守。
Nginx 可按实际流路径配置：

```nginx
location /admin/tasks/executions/watch/stream {
    proxy_pass http://app:8000;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 360s;
    gzip off;
}
```

WebSocket 代理必须转发 Upgrade、Connection、Origin 和 Authorization，并将消息大小与空闲超时设置为
不小于应用运行时限制：

```nginx
location /admin/tasks/executions/watch/ws {
    proxy_pass http://app:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Origin $http_origin;
    proxy_set_header Authorization $http_authorization;
    proxy_read_timeout 360s;
}
```

生产浏览器 WebSocket 默认使用短期单次票据并严格校验 Origin。Bearer SSE 使用 POST fetch streaming；
native EventSource 使用 GET 单次票据。禁止把长期 JWT 写入 SSE 或 WebSocket URL。

以上路径是未配置 `runtime.web.api_prefix` 时的当前生产绑定；配置前缀后应在 Nginx location 中同步添加。
生产 SSE 绑定当前使用 Bearer POST。WebSocket 浏览器票据路由
`/admin/tasks/executions/watch/ticket` 仅在 `require_browser_ticket=true` 时注册。

## 14. 2026-07-31 流式基建回归结果

- `docker compose -f compose.yml up -d --build`：通过，重建后的 app、PostgreSQL、Redis、RabbitMQ 均 healthy；app 使用新的配置化 Uvicorn 入口。
- `nox -s offline`：`786 passed, 1 deselected, 5 warnings`。
- `nox -s static`：Ruff、mypy、import-linter、Bandit、pip-audit、detect-secrets、锁文件与 Compose 配置全部通过。
- `nox -s regression`：`921 passed, 241 warnings`，无 skip/xfail，总覆盖率 `90.07%`；auth/security/task/persistence 关键域覆盖率均超过 `90%`。
- 真实 Redis 与真实 Uvicorn 定向流测试：`3 passed, 4 warnings`。
- 独立容量与真实网络稳定性测试：`2 passed, 16 warnings`；16 个并发编排流完成后任务数回落，SSE/WS 各 4 个并发连接反复 3 轮后，任务增长不超过 4，RSS 增长不超过 12 MiB。

现存告警来自 Starlette TestClient/httpx、passlib/argon2、funboost/Pydantic 与 websockets legacy API，
不影响当前断言和退出码。完整协议见
[WebSocket 与 SSE 统一流式协议](design_docs/WebSocket与SSE统一流式协议.md)。

## 15. 2026-08-15 生产更新与回滚记录

### 15.1 保留数据卷更新

本机生产后端使用项目名 `fastapi-web-production`、环境文件 `.env.production.local`，Compose 文件为
`compose.yml`、`compose.caddy.yml` 和 `compose.production.yml`。更新时保留现有命名卷，禁止执行
`docker compose down -v`：

```powershell
docker compose `
  --project-name fastapi-web-production `
  --env-file .env.production.local `
  -f compose.yml `
  -f compose.caddy.yml `
  -f compose.production.yml `
  up -d --build
```

Nuxt 生产前端使用独立项目 `typescript-web-production`，在
`E:\python_web_fastapi\typescript-web-nuxt` 使用相同文件组合与该目录的 `.env.production.local`
执行 `up -d --build`。Caddy 使用
`E:\python_web_fastapi\work\deploy\caddy\compose.yml`，项目名为 `fastapi-web-production-caddy`。

### 15.2 当前健康状态

2026-08-15 更新后，以下生产容器均为 `healthy`：

- `fastapi-web-production-app-1`；
- `fastapi-web-production-task-worker-1`；
- `fastapi-web-production-postgres-1`；
- `fastapi-web-production-redis-1`；
- `fastapi-web-production-rabbitmq-1`；
- `typescript-web-production-frontend-1`；
- `fastapi-web-production-caddy-caddy-1`。

`http://localhost:8080/health/ready` 返回 HTTP 200。测试依赖另由开发项目
`fastapi-web-skeleton` 提供 PostgreSQL `127.0.0.1:55432`、Redis `127.0.0.1:56379` 和 RabbitMQ
`127.0.0.1:5672`，不得把开发测试数据库与生产数据卷混用。

### 15.3 备份与回滚入口

更新前生产 PostgreSQL 备份为：

```text
E:\python_web_fastapi\work\.codex-tmp\production-backup-20260815-132848\pre-codex-unification-20260815-132848.dump
```

SHA-256：

```text
8ed90505c3c2fb1d8ba9bee664b665c557f04cbf01dae19fc491e239c4d668bf
```

应用回滚时先切回已验证的源码 revision 或镜像，再使用相同项目名、环境文件和 Compose 文件组合执行
`up -d --build`，不得删除命名卷。只有数据库迁移不向后兼容且应用回滚无法读取现有结构时，才停止应用写入，
校验上述 dump 摘要后恢复到独立数据库并切换连接；禁止直接覆盖仍在提供服务的生产数据库。

### 15.4 本轮门禁

- 后端真实依赖集成测试：`140 passed, 226 warnings`；
- 后端全量：`1296 passed, 241 warnings`；
- Ruff、mypy：通过；
- 前端 `pnpm verify`：`167 passed`，覆盖率、production build、Playwright `9 passed` 均通过；
- Windows Agent/MSI：0.1.10 本地安装、升级、维护、降级拒绝、卸载与重装通过。

## 16. 2026-08-16 Codex 稳定性更新

### 16.1 受影响服务更新

后端只重建并更新 `app` 与 `task-worker`。前端更新必须同时加载 `compose.caddy.yml`，否则重建后的
`frontend` 不会加入共享 edge 网络，Caddy 将无法解析 `frontend:3000`：

```powershell
docker compose `
  --project-name typescript-web-production `
  --env-file E:\python_web_fastapi\work\.env.production.local `
  -f compose.yml `
  -f compose.production.yml `
  -f compose.caddy.yml `
  up -d --no-deps frontend
```

本轮未执行 `down -v`。PostgreSQL、Redis、RabbitMQ 与 Caddy 容器和命名卷保持原实例，仅应用服务、
worker 和前端容器重建。

### 16.2 当前门禁

- migration head：`202608161230`，`codex_control_operation.projection` 已存在；
- 后端 Codex 集成与接口：`37 passed`；后端全量：`1327 passed, 241 warnings`；
- Ruff、mypy：通过，mypy 覆盖 `641` 个源码文件；
- 前端 `pnpm verify`：Vitest `32` 个文件 `178 passed`、覆盖率、production build、Playwright
  `9 passed`；
- 根入口和 `/health/ready`：HTTP `200`；全部生产容器 healthy；
- 应用日志未出现 WebSocket 关闭后发送异常。
