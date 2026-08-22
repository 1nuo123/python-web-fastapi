# 生产环境 Docker 一键部署与长期运维指南

## 1. 文档定位

本文是当前生产栈的部署与运维单一入口，适用于以下固定环境：

| 项目 | 当前值 |
| --- | --- |
| 云服务器 | 阿里云 ECS，实例 ID `i-2zegta8rnz1jge9pjt5n` |
| 公网 IP | `39.96.201.189` |
| 主私网 IP | `172.28.156.183` |
| 操作系统 | Ubuntu 24.04 64 位 |
| 实例规格 | `ecs.e-c1m1.large` |
| CPU / 内存 | 2 vCPU / 2 GiB |
| 系统盘 | 40 GiB ESSD Entry 云盘 |
| 公网带宽 | 3 Mbps，按固定带宽计费 |
| 付费类型 | 包年包月 |
| 到期时间 | 2027-08-22 23:59:59 |
| 自动续费 | 手动续费 |
| 创建时间 | 2026-08-22 12:14:00 |
| SSH 用户 | `root`，后续建议迁移到专用部署用户 |
| 后端仓库 | `git@github-backend:1nuo123/python-web-fastapi.git` |
| 前端仓库 | `git@github-frontend:1nuo123/typescript-web-nuxt.git` |
| 部署根目录 | `/opt/web` |
| 当前入口 | `https://nuotop.xyz` |
| 正式域名 | `nuotop.xyz` |
| 注册策略 | 允许公开注册 |
| 任务拓扑 | Web 生产者 + 独立 `task-worker` 消费者 |

本文从服务器拉取代码开始，覆盖首次初始化、发布、更新、备份、恢复、回滚、日志、监控、安全和域名 HTTPS 验收。Windows Agent 工作区属于用户电脑，不部署到云服务器。

## 2. 生产架构与边界

```text
Internet
   |
   | TCP 80/443, UDP 443 optional
   v
Caddy gateway
   |-- /auth, /health, /codex/events... -> FastAPI app:8000
   `-- page and /api proxy                  -> Nuxt frontend:3000

FastAPI app ---- PostgreSQL
      |          Redis
      |          RabbitMQ ---- task-worker
      `---- production edge network ---- Caddy/Nuxt
```

生产容器分为三个固定 Compose 项目：

| Compose 项目 | 服务 |
| --- | --- |
| `fastapi-web-production` | `postgres`、`redis`、`rabbitmq`、`migration`、`app`、`task-worker` |
| `typescript-web-production` | `frontend` |
| `fastapi-web-production-caddy` | `caddy` |

只有 Caddy 发布公网端口。PostgreSQL、Redis、RabbitMQ、FastAPI 和 Nuxt 不发布宿主机端口。

持久化边界：

| 命名卷 | 内容 | 备份定位 |
| --- | --- | --- |
| `fastapi-web-production_postgres_data` | 权威业务数据 | 必须使用 `pg_dump` 定期备份并异地保存 |
| `fastapi-web-production_redis_data` | Redis AOF、流式短期状态 | 重启连续性，不替代 PostgreSQL 备份 |
| `fastapi-web-production_rabbitmq_data` | RabbitMQ 队列状态 | 重启连续性，任务最终恢复仍以数据库 Outbox/执行记录为准 |
| `fastapi-web-production-caddy_caddy_data` | TLS 证书和 Caddy 状态 | 必须纳入主机或卷备份 |
| `fastapi-web-production-caddy_caddy_config` | Caddy 运行配置 | 可重建，但建议与证书卷一起保护 |

生产容器使用 JSON 日志轮转：单文件最大 `20m`，每个容器最多保留 5 个文件。它只能控制容器日志，不能控制 Docker 镜像和构建缓存占用。

## 3. 部署前检查

### 3.1 安全组

| 协议 | 端口 | 来源 | 说明 |
| --- | --- | --- | --- |
| TCP | 22 | 当前管理公网 IP `/32` | 不建议长期保留 `0.0.0.0/0` |
| TCP | 80 | `0.0.0.0/0` | HTTP 和证书签发跳转 |
| TCP | 443 | `0.0.0.0/0` | HTTPS |
| UDP | 443 | `0.0.0.0/0` | 可选，HTTP/3 |

不要开放 `5432`、`6379`、`5672`、`15672`、`8000` 或 `3000`。

### 3.2 Deploy Key

服务器的 `~/.ssh/config` 应存在 `github-backend` 和 `github-frontend` 两个 Host 别名，并分别使用对应私有仓库的只读 Deploy Key。

只读验证：

```bash
ssh -T github-backend
ssh -T github-frontend
git ls-remote git@github-backend:1nuo123/python-web-fastapi.git refs/heads/main
git ls-remote git@github-frontend:1nuo123/typescript-web-nuxt.git refs/heads/main
```

Deploy Key 只需要读权限。服务器不应直接提交或推送生产代码。

### 3.3 主机工具

```bash
git --version
docker --version
docker compose version
openssl version
sha256sum --version | head -n 1
curl --version | head -n 1
```

当前脚本要求 `git`、`docker`、`docker compose`、`openssl`、`sha256sum` 和 `curl`。

## 4. 首次一键部署

### 4.1 登录服务器

在 Windows PowerShell 执行：

```powershell
ssh -i "C:\Users\ThinkPad\.ssh\aliyun_fastapi" root@39.96.201.189
```

### 4.2 拉取两个仓库

```bash
install -d -m 755 /opt/web
cd /opt/web

git clone git@github-backend:1nuo123/python-web-fastapi.git
git clone git@github-frontend:1nuo123/typescript-web-nuxt.git
```

必须保持两个仓库为兄弟目录：

```text
/opt/web/
  python-web-fastapi/
  typescript-web-nuxt/
```

### 4.3 执行首次初始化

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh bootstrap
```

该命令一次完成：

1. 生成强随机 PostgreSQL、Redis、RabbitMQ、JWT 和管理员密钥。
2. 创建权限为 `600` 的后端、前端和一次性管理员环境文件。
3. 创建内部网络 `fastapi-web-production-edge`，固定子网 `172.30.0.0/24`。
4. 校验三个 Compose 项目。
5. 构建并启动 PostgreSQL、Redis、RabbitMQ、数据库迁移、FastAPI、Worker、Nuxt 和 Caddy。
6. 创建用户名为 `admin` 的初始管理员。
7. 通过本机 `127.0.0.1:443` 检查 `https://nuotop.xyz/health/ready` 的证书和路由。

`bootstrap` 只用于全新环境。只要任一生产环境文件已存在，它就会拒绝覆盖，防止意外重置密钥。

执行过程中会直接打印随机生成的管理员密码。不要使用 `tee` 把完整输出写入普通日志。将密码保存到密码管理器，完成登录验证后删除一次性文件：

```bash
rm -f /opt/web/python-web-fastapi/.env.initial-admin.local
```

删除后，日常 `deploy` 和 `update` 仍可正常运行，不会再次创建管理员。

### 4.4 首次验收

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh status
curl -I http://nuotop.xyz
curl -fsS https://nuotop.xyz/health/ready
```

浏览器访问：

```text
https://nuotop.xyz
```

需要确认：

- 页面加载正常。
- `admin` 可以登录。
- 新用户可以公开注册。
- `app` 和 `task-worker` 均为运行/健康状态。
- PostgreSQL、Redis、RabbitMQ 没有发布公网端口。
- 重启 Docker 后容器能按 `restart: unless-stopped` 自动恢复。

刷新令牌 Cookie 保持 `Secure`，Windows Agent 使用 WSS，因此首次部署前必须确保域名已解析到服务器且 TCP 80/443 可达。Caddy 会自动申请证书；证书签发成功后再完成浏览器和 Agent 验收。

### 4.5 Codex Remote 发布门禁

首次 `bootstrap` 生成的前端环境文件会将 `NUXT_PUBLIC_CODEX_FEATURE_ENABLED` 设为 `false`。这是故障关闭策略：在正式 Windows Agent 的 Authenticode 签名、TUF 发布元数据、下载与更新验收，以及域名 HTTPS/WSS 全链路验收全部完成前，生产入口不得展示 Codex Remote 下载或连接功能。

完成上述验收后，才允许在首次初始化时显式启用：

```bash
cd /opt/web/python-web-fastapi
PRODUCTION_CODEX_FEATURE_ENABLED=true bash deploy/production.sh bootstrap
```

已初始化的服务器不应重复执行 `bootstrap`。待服务器侧发布审批通过后，使用安全编辑器将 `/opt/web/typescript-web-nuxt/.env.production.local` 中的 `NUXT_PUBLIC_CODEX_FEATURE_ENABLED` 改为 `true`，然后执行 `bash deploy/production.sh deploy` 重新构建前端。关闭时将其改回 `false` 并重新执行 `deploy`；该开关只控制前端入口，不能替代后端授权、设备授权或 Agent 发布校验。

## 5. 统一运维命令

所有命令从后端目录执行：

```bash
cd /opt/web/python-web-fastapi
```

| 命令 | 用途 | 构建镜像 | 拉取代码 | 数据库备份 |
| --- | --- | --- | --- | --- |
| `bash deploy/production.sh bootstrap` | 仅首次初始化 | 是 | 否 | 否，新库 |
| `bash deploy/production.sh doctor` | 检查工具、仓库、环境和 Compose | 否 | 否 | 否 |
| `bash deploy/production.sh config` | 只校验 Compose | 否 | 否 | 否 |
| `bash deploy/production.sh deploy` | 发布当前检出的两个版本 | 是 | 否 | 否 |
| `bash deploy/production.sh update` | 两仓库快进更新并发布 | 是 | 是 | PostgreSQL 运行时自动备份 |
| `bash deploy/production.sh status` | 状态、版本、磁盘和就绪检查 | 否 | 否 | 否 |
| `bash deploy/production.sh logs backend` | 后端最近 200 行日志 | 否 | 否 | 否 |
| `bash deploy/production.sh logs frontend` | 前端最近 200 行日志 | 否 | 否 | 否 |
| `bash deploy/production.sh logs caddy` | Caddy 最近 200 行日志 | 否 | 否 | 否 |
| `bash deploy/production.sh follow backend` | 持续跟随后端日志 | 否 | 否 | 否 |
| `bash deploy/production.sh backup` | PostgreSQL 自定义格式备份 | 否 | 否 | 是 |
| `bash deploy/production.sh stop` | 停止全栈但保留卷 | 否 | 否 | 否 |
| `bash deploy/production.sh start` | 使用已有镜像启动 | 否 | 否 | 否 |

查看帮助：

```bash
bash deploy/production.sh help
```

## 6. 日常发布与更新

### 6.1 推荐的一键更新

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh doctor
bash deploy/production.sh update
```

`update` 会执行以下保护：

1. 要求前后端仓库都在 `main` 且没有未提交、未跟踪文件。
2. 分别 `fetch origin main`。
3. 确认远端可以从当前提交快进，不执行 rebase、force 或 hard reset。
4. PostgreSQL 已运行时先创建备份、校验文件和版本元数据。
5. 两个仓库分别执行 `git merge --ff-only origin/main`。
6. 构建新镜像、执行迁移并更新所有服务。
7. 完成就绪检查并打印容器状态。

环境文件被 Git 忽略，不会因 `update` 被覆盖。

### 6.2 人工审阅后发布

高风险版本建议先查看差异：

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh backup

git fetch origin main
git log --oneline --decorate HEAD..origin/main

git -C /opt/web/typescript-web-nuxt fetch origin main
git -C /opt/web/typescript-web-nuxt log --oneline --decorate HEAD..origin/main
```

确认后执行：

```bash
git pull --ff-only origin main
git -C /opt/web/typescript-web-nuxt pull --ff-only origin main
bash deploy/production.sh deploy
```

### 6.3 只重启与重新发布的区别

- `start`：使用已有镜像，不反映新代码和 Dockerfile 变化。
- `deploy`：重新构建当前代码，适用于代码、依赖、Dockerfile、Compose 或环境变量变化。
- `update`：先拉取两个仓库，再执行完整 `deploy`。

生产更新不要只执行裸 `docker compose restart`，因为它不会构建新代码，也不会执行新迁移。

## 7. 环境文件与密钥

首次初始化生成：

| 文件 | 内容 | 权限 | 生命周期 |
| --- | --- | --- | --- |
| `/opt/web/python-web-fastapi/.env.production.local` | 后端、数据库、缓存、消息队列和 Caddy 配置 | `600` | 长期保留 |
| `/opt/web/typescript-web-nuxt/.env.production.local` | Nuxt 生产配置 | `600` | 长期保留 |
| `/opt/web/python-web-fastapi/.env.initial-admin.local` | 一次性管理员创建密钥 | `600` | 登录验证后删除 |

检查权限：

```bash
stat -c '%a %U:%G %n' \
  /opt/web/python-web-fastapi/.env.production.local \
  /opt/web/typescript-web-nuxt/.env.production.local
```

应显示 `600 root:root`。不要把环境文件加入 Git、聊天记录、工单附件或普通日志。

环境文件需要单独做加密异地备份。PostgreSQL dump 不包含这些密钥；只有数据库备份而没有环境密钥，不能完整恢复原生产身份和会话边界。

密钥轮换注意事项：

- 修改 `JWT_SECRET` 会使现有登录令牌失效。
- 不能只修改 `POSTGRES_PASSWORD` 环境值；已有数据库用户密码不会自动变化。
- 不能只修改 `RABBITMQ_DEFAULT_PASS`；已有 RabbitMQ 用户不会自动重建。
- Redis 密码变化必须与所有依赖容器同步并安排维护窗口。

涉及 PostgreSQL、RabbitMQ 或 Redis 凭据轮换时，应先备份并执行服务内的密码修改，再更新环境文件和重建容器。

## 8. PostgreSQL 备份

### 8.1 手动备份

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh backup
```

默认输出到 `/var/backups/fastapi-web`，每次生成：

```text
postgres-YYYYMMDDTHHMMSSZ.dump
postgres-YYYYMMDDTHHMMSSZ.dump.sha256
postgres-YYYYMMDDTHHMMSSZ.dump.metadata
```

`.metadata` 记录备份时的前后端 Git 提交，回滚时必须保留。验证：

```bash
cd /var/backups/fastapi-web
sha256sum -c postgres-YYYYMMDDTHHMMSSZ.dump.sha256
```

### 8.2 异地保存

服务器本地备份不能防止云盘损坏、误删除或账号事件。备份完成后应复制到另一个受控存储，例如对象存储、另一台主机或加密的本地备份盘。

从 Windows 拉回备份示例：

```powershell
scp -i "C:\Users\ThinkPad\.ssh\aliyun_fastapi" `
  root@39.96.201.189:/var/backups/fastapi-web/postgres-YYYYMMDDTHHMMSSZ.dump* `
  E:\server-backups\fastapi-web\
```

推荐最小保留策略：最近 7 个日备、4 个周备、6 个月备。删除旧备份前，先确认异地副本和 SHA-256 校验可用。

### 8.3 定时备份

可以使用 root 的 cron：

```cron
15 3 * * * cd /opt/web/python-web-fastapi && /usr/bin/bash deploy/production.sh backup >> /var/log/fastapi-web-backup.log 2>&1
```

定时任务上线后必须观察至少一次真实成功结果，并为备份失败、云盘空间不足和备份文件长期未更新配置告警。长期更推荐 systemd timer 配合日志轮转和失败通知。

## 9. 数据库恢复

恢复是破坏性操作，不提供自动一键入口。必须在维护窗口中人工执行，并先保留当前数据库备份。

### 9.1 恢复前条件

1. 明确目标 dump、SHA-256 和 `.metadata` 中的前后端提交。
2. 在隔离环境演练恢复并完成登录、注册、任务和迁移验证。
3. 宣布维护窗口，停止公网写入。
4. 再备份一次当前数据库。
5. 确认要恢复的代码版本能读取目标数据库结构。

### 9.2 定义 Compose 命令

```bash
cd /opt/web/python-web-fastapi

BACKEND_COMPOSE=(docker compose --project-name fastapi-web-production --project-directory /opt/web/python-web-fastapi --env-file /opt/web/python-web-fastapi/.env.production.local -f /opt/web/python-web-fastapi/compose.yml -f /opt/web/python-web-fastapi/compose.production.yml -f /opt/web/python-web-fastapi/compose.caddy.yml)
FRONTEND_COMPOSE=(docker compose --project-name typescript-web-production --project-directory /opt/web/typescript-web-nuxt --env-file /opt/web/typescript-web-nuxt/.env.production.local -f /opt/web/typescript-web-nuxt/compose.yml -f /opt/web/typescript-web-nuxt/compose.production.yml -f /opt/web/typescript-web-nuxt/compose.caddy.yml)
CADDY_COMPOSE=(docker compose --project-name fastapi-web-production-caddy --project-directory /opt/web/python-web-fastapi/deploy/caddy --env-file /opt/web/python-web-fastapi/.env.production.local -f /opt/web/python-web-fastapi/deploy/caddy/compose.yml)
```

### 9.3 停止写入并恢复

将 `<dump-path>` 替换为已校验的文件：

```bash
DUMP_PATH=/var/backups/fastapi-web/postgres-YYYYMMDDTHHMMSSZ.dump

bash deploy/production.sh backup
"${CADDY_COMPOSE[@]}" stop
"${FRONTEND_COMPOSE[@]}" stop frontend
"${BACKEND_COMPOSE[@]}" stop app task-worker

"${BACKEND_COMPOSE[@]}" exec -T postgres \
  sh -c 'dropdb --if-exists --maintenance-db=postgres -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb --maintenance-db=postgres -U "$POSTGRES_USER" "$POSTGRES_DB"'

"${BACKEND_COMPOSE[@]}" exec -T postgres \
  sh -c 'exec pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$DUMP_PATH"
```

切换到 `.metadata` 记录的兼容代码版本后再发布。恢复完成后执行：

```bash
bash deploy/production.sh deploy
bash deploy/production.sh status
```

如果恢复失败，不要继续反复覆盖同一数据库；保留错误日志，重新创建隔离数据库定位 dump、版本或权限问题。

## 10. 应用回滚

### 10.1 数据库迁移向后兼容时

从最近备份 `.metadata` 读取提交：

```bash
cat /var/backups/fastapi-web/postgres-YYYYMMDDTHHMMSSZ.dump.metadata
```

然后切换到已知版本：

```bash
git -C /opt/web/python-web-fastapi fetch origin
git -C /opt/web/typescript-web-nuxt fetch origin

git -C /opt/web/python-web-fastapi checkout --detach <backend-commit>
git -C /opt/web/typescript-web-nuxt checkout --detach <frontend-commit>

cd /opt/web/python-web-fastapi
bash deploy/production.sh deploy
```

确认稳定后再决定是否在开发机创建正式回滚提交。不要从服务器直接 force push。

### 10.2 数据库迁移不向后兼容时

仅回滚镜像可能导致旧代码无法读取新结构。必须同时按上一节恢复与该提交对应的 PostgreSQL dump。生产迁移是否可逆，应在发布前审查，而不是故障后临时判断。

## 11. 日志与排障

常用命令：

```bash
bash deploy/production.sh logs backend
bash deploy/production.sh logs frontend
bash deploy/production.sh logs caddy

bash deploy/production.sh follow backend
bash deploy/production.sh follow frontend
bash deploy/production.sh follow caddy
```

后端组包含数据库、Redis、RabbitMQ、迁移、App 和 Worker。需要只看单一服务时使用完整 Compose 命令：

```bash
docker compose \
  --project-name fastapi-web-production \
  --project-directory /opt/web/python-web-fastapi \
  --env-file /opt/web/python-web-fastapi/.env.production.local \
  -f /opt/web/python-web-fastapi/compose.yml \
  -f /opt/web/python-web-fastapi/compose.production.yml \
  -f /opt/web/python-web-fastapi/compose.caddy.yml \
  logs --tail 200 --follow app
```

日志中禁止主动打印环境文件、JWT、Cookie、Deploy Key 或管理员密码。

## 12. 监控与容量

每次发布后：

```bash
bash deploy/production.sh status
docker stats --no-stream
free -h
df -h /
docker system df
```

当前 `40 GiB ESSD Entry` 系统盘建议阈值：

该实例只有 `2 GiB` 内存。生产部署时不要并行执行多个 Docker 构建或全量测试；如果构建阶段出现 OOM，应先在服务器上增加受控的交换空间或临时提升实例规格，再重新发布，不要通过降低容器安全限制解决内存不足。

| 使用率 | 动作 |
| --- | --- |
| 70% | 检查镜像、构建缓存、备份增长和异常日志 |
| 80% | 清理已确认无用的悬空镜像/旧构建缓存，迁移异地备份 |
| 90% | 停止非必要构建，优先扩容云盘并处理告警 |

发布成功且确认无需旧的悬空镜像后，可以执行：

```bash
docker image prune -f
docker builder prune --filter 'until=168h'
```

执行前先看 `docker system df`。不要使用 `docker volume prune`，也不要把 `docker system prune --volumes` 作为日常清理命令。

最低监控项：

- `GET /health/live` 和 `GET /health/ready`。
- 5xx、登录失败、注册失败和 Caddy 反向代理错误率。
- PostgreSQL 连接、磁盘、慢查询和备份新鲜度。
- Redis 内存、AOF 状态和连接失败。
- RabbitMQ 队列积压、未确认消息和消费者数量。
- `task-worker` 存活与任务失败率。
- CPU、内存、根磁盘和 Docker 数据目录空间。
- TLS 证书剩余时间，启用域名后必须告警。

## 13. 正式域名与 HTTPS 启用

域名可用后按以下步骤闭环：

1. 在阿里云 DNS 添加主机记录 `@`、类型 `A`、记录值 `39.96.201.189`、TTL `600`。
2. 确认安全组开放 TCP 80/443，UDP 443 可选。
3. 确认后端 `/opt/web/python-web-fastapi/.env.production.local` 包含：

```dotenv
CADDY_SITE_ADDRESS=nuotop.xyz
```

4. 生产流配置已固定为真实 HTTPS Origin：

```toml
allowed_origins = [
  "https://nuotop.xyz",
]
```

该配置属于代码，应由服务器通过仓库更新获取，不要在服务器直接修改源码。

5. 发布：

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh update
```

6. 验收：

```bash
curl -I http://nuotop.xyz
curl -I https://nuotop.xyz
curl -fsS https://nuotop.xyz/health/ready
```

浏览器必须验证登录刷新、退出、公开注册、WebSocket 重连、移动网络切换和页面快照恢复。Windows Agent 必须验证下载、设备授权、WSS 重连和远程任务执行。生产入口只使用域名 HTTPS，不把裸 IP HTTP 作为业务入口。

## 14. 主机安全最佳实践

当前使用 `root` 可以完成首次部署，但长期建议：

1. 创建专用部署用户，只授予必要的 sudo 权限。
2. 验证新用户密钥登录后，再禁用 SSH 密码登录。
3. 根据实际管理方式限制或禁用 root 远程登录。
4. 将安全组 22 端口来源改为固定管理 IP `/32`，IP 变化前先添加新规则，避免锁死。
5. 启用系统安全更新，并在维护窗口重启内核。
6. 保护 `/var/lib/docker`、`/opt/web`、`/var/backups/fastapi-web` 和 SSH 私钥。
7. 认识到 Docker daemon 和 `docker` 用户组等价于 root 权限。
8. Deploy Key 使用只读权限，前后端仓库使用不同密钥。
9. 每季度检查不再使用的 SSH Key、GitHub Deploy Key、安全组规则和管理员账号。

## 15. 常见故障

| 现象 | 检查 | 处理 |
| --- | --- | --- |
| `Permission denied (publickey)` | `ssh -T github-backend/frontend` | 检查 Host 别名、私钥权限和 Deploy Key 是否绑定正确仓库 |
| `bootstrap` 拒绝覆盖环境文件 | 检查 `.env.production.local` | 已初始化时使用 `deploy`；不要删除长期环境文件重跑 bootstrap |
| edge 网络子网错误 | `docker network inspect fastapi-web-production-edge` | 确认无容器依赖后重建为内部 `172.30.0.0/24`；不要盲删正在使用的网络 |
| 80/443 端口占用 | `ss -lntup | grep -E ':80|:443'` | 停止冲突的 Nginx/Apache/旧 Caddy，或明确迁移入口 |
| readiness 失败 | `logs backend`、`logs caddy` | 优先看 migration、app、Redis、RabbitMQ 健康状态 |
| migration 失败 | 后端 migration 日志 | 不要跳过迁移强行启动旧/新代码；按备份和版本兼容性处理 |
| Caddy 返回 502 | `logs caddy`、前端/后端 `ps` | 检查共享 edge 网络、服务别名和容器健康 |
| 磁盘接近满 | `df -h /`、`docker system df` | 转移旧备份，清理悬空镜像和过期构建缓存，必要时扩容云盘 |
| HTTP 下登录很快失效 | 浏览器 Cookie 和网络面板 | 临时 HTTP 不支持 Secure refresh Cookie，切换正式 HTTPS |
| Worker 不消费 | RabbitMQ 队列、`task-worker` 日志 | 确认独立 Worker 正常运行、消费者存在、消息未持续积压 |

## 16. 明确禁止的操作

生产日常运维禁止：

```text
docker compose down -v
docker volume prune
docker system prune --volumes
git reset --hard origin/main
git push --force
```

同样禁止：

- 未备份就执行数据库迁移或恢复。
- 在服务仍接受写入时覆盖数据库。
- 将真实 `.env`、dump、私钥提交到 Git。
- 直接暴露 PostgreSQL、Redis、RabbitMQ 管理端口。
- 为解决启动失败而降低生产密钥、安全校验、Origin 或可信代理限制。
- 在没有记录前后端提交的情况下执行发布。

## 17. 运维检查表

### 每次发布

- [ ] 前后端门禁已通过。
- [ ] 仓库工作树干净，版本已记录。
- [ ] PostgreSQL 备份和 SHA-256 已生成。
- [ ] 使用 `update` 或审阅后 `deploy`，没有强制覆盖 Git 历史。
- [ ] migration 成功。
- [ ] App、Worker、前端、Caddy 健康。
- [ ] 页面、登录、注册和关键任务通过。
- [ ] 磁盘、内存和队列没有异常增长。

### 每日

- [ ] readiness 正常。
- [ ] 备份文件更新且异地同步成功。
- [ ] 无持续 5xx、认证异常或任务积压。
- [ ] 根磁盘低于告警阈值。

### 每周

- [ ] 抽查备份 SHA-256。
- [ ] 检查 Docker 镜像和构建缓存占用。
- [ ] 检查系统更新和异常 SSH 登录。
- [ ] 检查 PostgreSQL、Redis、RabbitMQ 容量趋势。

### 每季度

- [ ] 在隔离环境完成一次真实恢复演练。
- [ ] 复核 Deploy Key、安全组和管理员账号。
- [ ] 评估密钥轮换和操作系统重启窗口。
- [ ] 验证正式 HTTPS 证书、登录刷新和 WSS 链路。

## 18. 快速命令卡

```bash
cd /opt/web/python-web-fastapi

# 首次部署，仅一次
bash deploy/production.sh bootstrap

# 日常检查
bash deploy/production.sh doctor
bash deploy/production.sh status

# 一键拉取、备份、构建、迁移和发布
bash deploy/production.sh update

# 当前代码重新发布
bash deploy/production.sh deploy

# 备份
bash deploy/production.sh backup

# 日志
bash deploy/production.sh logs backend
bash deploy/production.sh follow caddy

# 停启，保留全部命名卷
bash deploy/production.sh stop
bash deploy/production.sh start
```

本文中的脚本和 Compose 文件是执行入口；历史 Docker 文档只用于理解开发环境，不应覆盖本指南的生产命令。
