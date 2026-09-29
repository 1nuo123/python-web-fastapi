# 生产环境 Docker 部署与长期运维指南

## 文档边界

本文是通用生产 runbook。真实主机地址、域名、仓库地址、部署目录、SSH 用户、密钥和 Secret 必须由受控部署系统注入，不能写入仓库文档。示例中的 `<...>` 均为部署参数，占位符不能直接用于生产。

生产拓扑保持清晰的单一入口：Caddy 只暴露 80/443，FastAPI、Nuxt、PostgreSQL、Redis、RabbitMQ 和 task-worker 仅在内部 Compose 网络通信。数据库是业务事实源，Outbox/执行记录负责任务投递与恢复，Redis 和 RabbitMQ 的卷只提供重启连续性，不替代数据库备份。

## 部署参数

在受控终端设置以下变量，或通过 Secret Manager/CI 注入：

```bash
export DEPLOY_HOST='<production-host>'
export DEPLOY_USER='<deploy-user>'
export DEPLOY_ROOT='<deployment-root>'
export SITE_ADDRESS='<production-domain>'
export BACKEND_REPO='<backend-repository>'
export FRONTEND_REPO='<frontend-repository>'
export SSH_KEY='<path-to-deployment-key>'
```

部署账号使用最小权限，Docker 管理权限、备份目录和发布目录按职责授予。禁止使用 `root` 作为日常发布账号，禁止把私钥、密码或初始管理员凭据写入命令历史、日志或文档。

## 首次部署

1. 在受控终端验证 SSH 主机指纹，并使用专用部署账号连接：

```bash
ssh -i "$SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST"
```

2. 在服务器创建部署根目录并拉取固定提交：

```bash
install -d -m 750 "$DEPLOY_ROOT"
git clone "$BACKEND_REPO" "$DEPLOY_ROOT/backend"
git clone "$FRONTEND_REPO" "$DEPLOY_ROOT/frontend"
git -C "$DEPLOY_ROOT/backend" checkout --detach <backend-commit>
git -C "$DEPLOY_ROOT/frontend" checkout --detach <frontend-commit>
```

3. 通过受控 Secret 注入生成后端和前端生产环境文件，权限设为 `600`。生产环境不得从开发 `.env` 文件回退到弱默认值。一次性 bootstrap 凭据成功使用后立即吊销并删除。

4. 先构建镜像，再按 `postgres`、`redis`、`rabbitmq`、`migration`、`app`、`task-worker`、`frontend`、`caddy` 顺序启动。Compose 命令必须显式指定项目名、环境文件和生产 overlay：

```bash
docker compose --project-name <backend-project> \
  --project-directory "$DEPLOY_ROOT/backend" \
  --env-file "$DEPLOY_ROOT/backend/.env.production.local" \
  -f "$DEPLOY_ROOT/backend/compose.yml" \
  -f "$DEPLOY_ROOT/backend/compose.production.yml" \
  up -d --build postgres redis rabbitmq migration app task-worker

docker compose --project-name <frontend-project> \
  --project-directory "$DEPLOY_ROOT/frontend" \
  --env-file "$DEPLOY_ROOT/frontend/.env.production.local" \
  -f "$DEPLOY_ROOT/frontend/compose.yml" \
  -f "$DEPLOY_ROOT/frontend/compose.production.yml" \
  up -d --build frontend
```

5. 启动 Caddy 及其共享 edge 网络，然后执行分层验收。Caddy 使用后端仓库 `deploy/caddy/compose.yml`，其 `EDGE_NETWORK_NAME` 必须与后端 `compose.caddy.yml` 和生产前端接线一致。不要使用 `down -v` 作为普通更新操作。

```bash
docker compose --project-name <edge-project> \
  --project-directory "$DEPLOY_ROOT/backend/deploy/caddy" \
  --env-file "$DEPLOY_ROOT/backend/.env.production.local" \
  -f "$DEPLOY_ROOT/backend/deploy/caddy/compose.yml" \
  up -d caddy
```

生产 Compose 应拆分为后端项目、前端项目和 edge/Caddy 项目；只有 Caddy 发布宿主机 80/443 端口。PostgreSQL、Redis、RabbitMQ、FastAPI 和 Nuxt 不发布宿主机端口。命名卷的恢复优先级如下：PostgreSQL 业务数据必须做 `pg_dump`，Redis/RabbitMQ 只提供重启连续性，Caddy 数据保存证书和网关状态。容器日志启用 JSON 轮转，并单独监控 Docker 镜像、构建缓存和备份目录空间。

首次部署前检查主机工具和资源：

```bash
git --version
docker --version
docker compose version
openssl version
sha256sum --version | head -n 1
curl --version | head -n 1
free -h
swapon --show
df -h /
```

服务器容量必须按实际规格选择 Compose resource profile。小规格主机应串行构建镜像，必要时配置受控 swap；swap 只能吸收构建尖峰，不能替代扩容。

## 迁移与发布

当前源码 Alembic head 以 `src/infrastructure/persistence/alembic/versions` 的 revision graph 为准；文档当前记录的 head 是 `202609291900`。每次发布前在隔离环境执行：

```bash
docker compose --project-name <backend-project> \
  --project-directory "$DEPLOY_ROOT/backend" \
  --env-file "$DEPLOY_ROOT/backend/.env.production.local" \
  -f "$DEPLOY_ROOT/backend/compose.yml" \
  -f "$DEPLOY_ROOT/backend/compose.production.yml" \
  run --rm migration
```

迁移必须先完成并验证，再切换依赖新结构的应用镜像。迁移脚本应保持向后兼容；不可逆迁移必须在发布说明中给出数据库恢复方案。源码 head、部署脚本声明和本文件不一致时，发布立即停止，先更新事实记录。

更新时固定提交、备份数据库、构建新镜像、运行迁移、滚动重建 app/worker/frontend，并检查旧容器已退出。不要只执行 `docker compose restart`，它不会构建代码，也不会执行新迁移。

推荐发布命令：

```bash
cd "$DEPLOY_ROOT/backend"
<deploy-script> doctor
<deploy-script> backup
<deploy-script> update
<deploy-script> status
```

发布前应确认前后端工作树干净、提交已记录、数据库备份和校验文件已生成、迁移在隔离环境通过。`update` 只能快进到已审阅提交，不能在服务器执行强制重置或直接推送代码。

## 配置与 Secret 生命周期

生产环境文件由 Secret Manager、Docker secrets 或受控 CI 变量生成，权限设为 `600`，不得从开发 `.env` 回退到弱默认值。数据库、Redis、RabbitMQ、JWT、bootstrap 和 TLS 相关凭据分开管理；一次性 bootstrap 凭据成功使用后立即吊销并删除。Secret 轮换应先备份并在维护窗口内同步更新依赖服务，不能只改环境文件而不修改服务端凭据。

常规部署检查：

```bash
stat -c '%a %U:%G %n' "$DEPLOY_ROOT/backend/.env.production.local" \
  "$DEPLOY_ROOT/frontend/.env.production.local"
```

真实环境文件、数据库 dump、私钥、token 和日志不得提交 Git、写入聊天记录、工单附件、普通备份或构建产物。发现曾经暴露的凭据时按已泄露处理并轮换，不要只依赖 `.gitignore`。

## 验收

```bash
curl -fsS "https://$SITE_ADDRESS/health/live"
curl -fsS "https://$SITE_ADDRESS/health/ready"
docker compose --project-name <backend-project> ps
docker compose --project-name <backend-project> logs --tail=200 app task-worker migration
```

验收至少覆盖登录、权限拒绝、数据库读写、任务提交与消费、实时连接、前端静态资源和 Caddy HTTPS。进程存活不能替代 worker 的 Broker、consumer 和 handler readiness 检查。

发布后保存以下证据：代码提交、migration head、配置 profile、容器状态、`/health/live` 与 `/health/ready` 响应、任务提交和消费结果、实时连接结果、备份文件校验值以及异常日志摘要。任何一项失败都不能标记发布完成。

## 备份与恢复

使用受控备份任务执行 `pg_dump` 并异地保存，定期验证可恢复性。Redis、RabbitMQ、Caddy 状态卷按恢复目标备份，但不能替代 PostgreSQL 备份。恢复演练必须在隔离环境完成登录、迁移、任务和实时连接验证后再考虑生产切换。

建议每次数据库备份同时写出校验和、代码提交、数据库 head、备份时间和环境标识元数据。备份保留策略应至少覆盖日备、周备和月备，并为备份失败、空间不足和备份过期设置告警。恢复前先保留当前数据库备份，停止公网写入，在隔离环境验证目标 dump 与目标代码兼容，再执行恢复。

通用恢复步骤：

```bash
<compose> stop gateway frontend app task-worker
<compose> exec -T postgres sh -c \
  'dropdb --if-exists --maintenance-db=postgres -U "$POSTGRES_USER" "$POSTGRES_DB" && \
   createdb --maintenance-db=postgres -U "$POSTGRES_USER" "$POSTGRES_DB"'
<compose> exec -T postgres sh -c \
  'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < <dump-path>
<deploy-script> deploy
<deploy-script> status
```

恢复失败时保留日志并转移到隔离数据库定位问题，禁止反复覆盖同一生产库。

## 回滚

回滚前记录代码提交、数据库 head、Outbox 状态计数和队列深度。兼容迁移可回滚镜像并继续运行；不兼容迁移必须同时恢复与旧代码匹配的数据库备份。Secret 轮换只能通过受控注入回滚，禁止恢复工作区明文文件。

回滚只允许切换到已知提交或已验证备份。迁移不可逆时，旧镜像不能单独回滚；必须同时恢复匹配的数据库快照，并重新执行迁移和健康检查。回滚完成后复核登录、任务消费、Outbox 重扫、实时连接、前端静态资源和 TLS。

## 日志、监控与容量

```bash
<deploy-script> status
<deploy-script> logs backend
<deploy-script> logs frontend
<deploy-script> logs gateway
docker stats --no-stream
docker system df
free -h
df -h /
```

至少监控 `/health/live`、`/health/ready`、5xx、认证失败、数据库连接、Redis 内存、RabbitMQ 队列积压/未确认消息/消费者数量、task-worker 消费状态、Outbox retry/unknown/dead-letter、CPU/内存/磁盘、备份新鲜度和 TLS 证书剩余时间。进程存活但没有消费者或 handler binding 时，worker readiness 必须失败。

磁盘达到 70% 时检查镜像、构建缓存、日志和备份增长；达到 80% 时迁移异地备份并清理已确认无用的悬空镜像；达到 90% 时停止非必要构建并优先扩容。不要使用 `docker volume prune` 清理业务卷。

## 常见故障

| 现象 | 检查 | 处理 |
| --- | --- | --- |
| SSH 公钥认证失败 | 主机指纹、部署账号、密钥权限 | 通过受控密钥轮换修复，不把私钥写入文档 |
| migration 失败 | migration 日志、数据库 head、环境文件 | 停止应用启动，按备份和兼容窗口处理，不跳过迁移 |
| readiness 失败 | app、数据库、Redis、RabbitMQ、worker 日志 | 先确认依赖 ready，再重建应用容器 |
| Caddy 返回 502 | edge 网络、服务名、容器健康状态 | 恢复共享网络和上游服务，不开放后端公网端口 |
| Worker 不消费 | Broker 队列、consumer 数量、handler binding、health probe | 修复 worker readiness；不要只重启生产者 |
| 磁盘接近满 | `df -h`、`docker system df`、备份目录 | 迁移备份、清理悬空镜像/缓存，必要时扩容 |
| HTTPS/WSS 失败 | DNS、80/443、证书、Origin、Upgrade 头 | 按网关验收修复，避免降级到裸 IP 或明文凭据 |

## 禁止操作与检查表

生产日常运维禁止：

```text
docker compose down -v
docker volume prune
docker system prune --volumes
git reset --hard origin/main
git push --force
```

每次发布必须确认：

- [ ] 前后端门禁通过，提交和配置版本已记录。
- [ ] 数据库备份、校验和、migration head 已保存。
- [ ] migration 成功，app、worker、frontend、gateway healthy。
- [ ] 登录、权限拒绝、任务提交/消费、实时连接和关键页面通过。
- [ ] 队列、Outbox、磁盘、内存、备份新鲜度无异常。

每日检查 readiness、备份异地同步和持续 5xx/任务积压；每周抽查备份校验和容量趋势；每季度在隔离环境完成恢复演练并复核部署账号、密钥、网络规则和 TLS/WSS。

## 安全与文档维护

- 通用仓库文档不得包含真实 IP、实例 ID、域名、部署路径、私钥路径、root 登录命令或 Secret 值。
- 真实 runbook、主机清单和凭据引用放入受控文档系统。
- 发布前扫描源码、忽略文件、文档和构建产物中的 Secret 与基础设施标识。
- 每次迁移新增或修改后，同步更新当前 head、兼容窗口、回滚边界和验证命令；历史文档必须标明适用提交和日期。
