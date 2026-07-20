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
