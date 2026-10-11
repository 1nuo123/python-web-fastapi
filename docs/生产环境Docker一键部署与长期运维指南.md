# 生产环境 CI 镜像部署与运维指南

## 适用范围

本项目生产环境采用单机 Docker Compose 运行，前端、后端、migration 和 task-worker 镜像全部由 GitHub Actions 构建并推送到 GHCR。生产服务器只负责拉取已经构建完成的镜像、执行迁移、启动容器和检查健康状态。

生产服务器不执行前端 Nuxt 构建，也不执行后端 Docker 构建。这样可以避免 2 核 2G 主机在构建阶段耗尽内存，并让每次发布都能根据镜像 Digest 审计和回滚。

生产入口只有 Caddy。FastAPI、Nuxt、PostgreSQL、Redis、RabbitMQ 和 task-worker 通过 Compose 内部网络通信。

## 发布事实

两个仓库的生产镜像由以下 workflow 生成：

- 后端：`.github/workflows/production-image.yml`
- 前端：`.github/workflows/production-image.yml`

每次 `main` 提交都会生成两个标签：

```text
ghcr.io/1nuo123/python-web-fastapi:<commit-sha>
ghcr.io/1nuo123/python-web-fastapi:main

ghcr.io/1nuo123/typescript-web-nuxt:<commit-sha>
ghcr.io/1nuo123/typescript-web-nuxt:main
```

生产部署只使用完整 commit SHA 标签，并在服务器拉取后解析为不可变 Digest。 `:main` 仅用于人工检查，不作为生产部署依据。

后端镜像同时服务于：

- `migration`
- `app`
- `task-worker`

前端镜像只服务于 `frontend`。

## 首次准备

### GitHub Actions

两个仓库必须启用 GitHub Actions，并允许 workflow 使用：

```text
contents: read
packages: write
```

workflow 使用仓库内置的 `GITHUB_TOKEN` 推送 GHCR，不需要把个人 Token 写入仓库。
workflow 同时生成 BuildKit provenance 和 SBOM，便于后续核对镜像来源。

首次运行后，在 GHCR 中确认以下两个 package 存在：

```text
ghcr.io/1nuo123/python-web-fastapi
ghcr.io/1nuo123/typescript-web-nuxt
```

### 服务器 GHCR 只读登录

服务器只需要读取 package 的权限。使用一个仅具备 `read:packages` 的 GitHub Token，在服务器执行一次：

```bash
read -r -s GHCR_READ_TOKEN
printf '%s' "$GHCR_READ_TOKEN" | docker login ghcr.io \
  --username 1nuo123 \
  --password-stdin
unset GHCR_READ_TOKEN
```

不要把 Token 写入 `.env`、Git、部署脚本或命令行历史。

### 生产环境文件

保留现有受控文件：

```text
/opt/web/python-web-fastapi/.env.production.local
/opt/web/typescript-web-nuxt/.env.production.local
```

文件权限必须为 `600`。镜像地址不写入环境文件，部署脚本根据两个仓库当前提交自动生成对应的 SHA 镜像引用。

## 发布前流程

每个仓库推送 `main` 后，必须等待对应的 `Build production image` workflow 成功。只有两个 workflow 都成功，服务器才允许发布。

本地 PowerShell 推送示例：

```powershell
Set-Location E:\python_web_fastapi\work
git status --short
git push origin main

Set-Location E:\python_web_fastapi\typescript-web-nuxt
git status --short
git push origin main
```

推送完成后，在 GitHub Actions 页面确认两个 workflow 的构建和推送步骤都成功。失败的 workflow 不得进入部署阶段。

## 生产发布命令

SSH 连接：

```powershell
ssh -i "$SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST"
```

进入服务器后：

```bash
cd /opt/web/python-web-fastapi || exit 1

export PRODUCTION_FRONTEND_ROOT=/opt/web/typescript-web-nuxt
export COMPOSE_PROFILES=task-worker

deploy_log="/root/codex-deploy-$(date +%Y%m%d-%H%M%S).log"

nohup bash -c '
  set -uo pipefail
  result=0
  bash deploy/production.sh update || result=$?
  if [ "$result" -eq 0 ]; then bash deploy/production.sh status || result=$?; fi
  if [ "$result" -eq 0 ]; then curl --fail --silent --show-error https://<production-domain>/health/ready || result=$?; fi
  printf "\nDEPLOY_EXIT_CODE=%s\n" "$result"
  exit "$result"
' >"$deploy_log" 2>&1 < /dev/null &

echo "$deploy_log"
tail -f "$deploy_log"
```

`update` 的执行链路是：

```text
fetch 两个 main
→ 检查 origin/main 对应的两个 CI 镜像是否存在
→ 创建 PostgreSQL 备份
→ fast-forward 两个仓库
→ 拉取后端和前端镜像
→ 解析镜像 Digest
→ 使用 Digest 启动 Compose
→ 执行 migration
→ 启动 app、task-worker、frontend、Caddy
→ readiness 检查
```

脚本会在 CI 镜像不存在时提前失败，不会继续切换仓库或启动半套版本。

看到以下结果才算发布成功：

```text
DEPLOY_EXIT_CODE=0
```

如果 SSH 断开，重新连接后只查看当前日志，不要再次启动部署：

```bash
deploy_log="$(ls -1t /root/codex-deploy-*.log | head -n 1)"
tail -n 120 -f "$deploy_log"
```

## 发布后检查

```bash
cd /opt/web/python-web-fastapi

export PRODUCTION_FRONTEND_ROOT=/opt/web/typescript-web-nuxt
export COMPOSE_PROFILES=task-worker

bash deploy/production.sh status
curl --fail --silent --show-error https://<production-domain>/health/live
curl --fail --silent --show-error https://<production-domain>/health/ready
```

检查 Compose 中的镜像必须是 Digest 引用：

```bash
docker inspect fastapi-web-production-app-1 \
  --format '{{.Config.Image}}'

docker inspect typescript-web-production-frontend-1 \
  --format '{{.Config.Image}}'
```

必须确认：

- app healthy
- task-worker healthy
- frontend healthy
- Caddy healthy
- migration 已成功退出
- `/health/live` 成功
- `/health/ready` 成功
- 登录、Codex 实时连接、消息发送和任务消费通过端到端验收

## 回滚

回滚只能使用已经成功部署过的镜像 Digest。先停止自动更新，再设置旧的后端和前端 Digest：

```bash
cd /opt/web/python-web-fastapi

export PRODUCTION_FRONTEND_ROOT=/opt/web/typescript-web-nuxt
export COMPOSE_PROFILES=task-worker
export BACKEND_IMAGE='ghcr.io/1nuo123/python-web-fastapi@sha256:<known-good-backend-digest>'
export FRONTEND_IMAGE='ghcr.io/1nuo123/typescript-web-nuxt@sha256:<known-good-frontend-digest>'

bash deploy/production.sh deploy
bash deploy/production.sh status
```

数据库迁移必须保持向后兼容。不可逆迁移不能只回滚镜像；必须同时恢复与旧代码匹配的 PostgreSQL 备份，并重新执行迁移和健康检查。

## 备份

常规发布会自动创建 PostgreSQL custom-format 备份、校验文件和提交元数据。也可以手动执行：

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh backup
```

禁止使用以下命令：

```text
docker compose down -v
docker volume prune
docker system prune --volumes
git reset --hard origin/main
git push --force
```

## 故障处理

### workflow 成功但服务器提示镜像不存在

确认：

```bash
docker login ghcr.io
docker pull ghcr.io/1nuo123/python-web-fastapi:<backend-commit-sha>
docker pull ghcr.io/1nuo123/typescript-web-nuxt:<frontend-commit-sha>
```

如果 package 是私有的，检查服务器 Token 是否仍具备 `read:packages`。

### Docker pull 返回 502 或超时

这是服务器到镜像仓库或镜像加速站的网络问题。不要重复启动多份部署进程；先确认：

```bash
docker pull ghcr.io/1nuo123/typescript-web-nuxt:<frontend-commit-sha>
```

### readiness 失败

```bash
bash deploy/production.sh status
bash deploy/production.sh logs backend
bash deploy/production.sh logs frontend
bash deploy/production.sh logs caddy
```

先处理 migration、数据库、Redis、RabbitMQ 和 task-worker 的健康状态，再重试启动。

### 磁盘不足

```bash
df -h /
docker system df
```

只能清理已确认无用的悬空镜像和构建缓存，禁止清理业务卷。

## 维护边界

部署相关改动必须同步检查：

- 两个 `production-image.yml`
- 后端 `compose.production.yml`
- 前端 `compose.production.yml`
- `deploy/production.sh`
- `deploy/run-production-ip.sh`
- 本文档

业务代码、API、数据库模型和 Agent 协议不属于本部署方案的修改范围。


