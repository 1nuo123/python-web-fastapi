# 本次安装连接与 CLI 兼容改造发布命令

适用日期：2026-10-20。顺序为提交两个仓库 → 等待 CI 镜像 → 服务器统一更新 → 实际连接/任务验收 → 手动发布内部 MSI → 同步下载清单并再次部署。发布由用户执行；本命令单未执行 commit、push、部署或远端发布。

已核对后端和前端均为 `main`，远端分别是 `1nuo123/python-web-fastapi`、`1nuo123/typescript-web-nuxt`。服务器目录采用现有运维指南的 `/opt/web/python-web-fastapi` 和 `/opt/web/typescript-web-nuxt`。SSH 地址和密钥由交互输入提供，不能把 CDN 域名当 SSH 源站。按用户决定，本次手动发布不配置 Azure/TUF。

本次直接发布已完成冻结 EXE、本机卸装及三版本 CLI 验收的 0.1.42 原始产物，不重建同版本。最低安全版本保留当前 0.1.31。内部包仍不启用自动更新，后续手动覆盖安装。24 小时验收仍在运行，未计为通过。

## 1. 本机准备（PowerShell 7.4 或更新版本）

当前执行环境未找到 GitHub CLI。若你的终端也没有 `gh`，先执行安装，然后重新打开 PowerShell：

```powershell
winget install --id GitHub.cli --exact --source winget
```

后续本机命令在同一个 PowerShell 会话执行：

```powershell
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$BackendRoot = 'E:\python_web_fastapi\work'
$FrontendRoot = 'E:\python_web_fastapi\typescript-web-nuxt'
$BackendRepo = '1nuo123/python-web-fastapi'
$FrontendRepo = '1nuo123/typescript-web-nuxt'

gh auth status
# 仅在尚未登录时执行：gh auth login --hostname github.com --git-protocol https --web
```

## 2. 更新两个源码仓库

工作区有大量与本次任务无关的文档归档/删除，下面只提交本次代码、明确文档和发布门需要的九份证据。不要替换成 `git add .` 或 `git add -A`。当前这些代码目录中的改动均已定位为本次改造；如果执行前又产生其他改动，先调整暂存范围。

```powershell
Set-Location $BackendRoot
if ((git branch --show-current) -ne 'main') { throw '后端当前分支不是 main。' }
if (git diff --cached --name-only) { throw '后端已有暂存内容，请先确认其归属。' }
git fetch origin main
git merge-base --is-ancestor origin/main HEAD

git add -- `
  .github/workflows/codex-agent-release.yml `
  .github/workflows/codex-agent-publish.yml `
  config/runtime/codex_control_runtime/codex_control_runtime_base.toml `
  packaging/windows/wix/Product.wxs `
  protocol/codex_app_server/0.162.0 `
  protocol/codex_app_server/0.163.0 `
  scripts/codex/acceptance `
  scripts/codex/verify_compatibility_release.py `
  deploy/production.sh `
  src `
  docs/project_manual/04_infrastructure/codex_agent_production_release.md `
  docs/project_manual/04_infrastructure/codex_connection_release_commands.md `
  docs/archive/2026/2026_10/2026_10_20_Codex安装连接体验与CLI版本兼容改进方案.md

foreach ($CliVersion in @('0.145.0', '0.162.0', '0.163.0')) {
  git add -- "artifacts/codex-connection/cli-$CliVersion.json" `
    "artifacts/codex-connection/approvals-$CliVersion.json" `
    "artifacts/codex-connection/approvals-extra-$CliVersion.json"
}

# 发布证据门：只读核对已完成的真实验收，不运行单元测试。
& .venv/Scripts/python.exe -m scripts.codex.verify_compatibility_release
git diff --cached --stat
git commit -m 'feat(codex): unify connection recovery and verified CLI compatibility'
$BackendSha = (git rev-parse HEAD).Trim()
git push origin main

Set-Location $FrontendRoot
if ((git branch --show-current) -ne 'main') { throw '前端当前分支不是 main。' }
if (git diff --cached --name-only) { throw '前端已有暂存内容，请先确认其归属。' }
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git add -- `
  app/composables/useCodexRealtime.client.ts `
  app/composables/useCodexEnrollment.ts `
  'app/pages/codex/tasks/[threadId].vue' `
  app/pages/codex/verify-device.vue `
  app/services/api/codex-enrollment.ts `
  app/services/api/codex-realtime.ts `
  app/stores/codex-approvals.ts `
  app/stores/codex-realtime.ts `
  app/stores/codex-session.ts `
  app/types/codex-enrollment.ts `
  app/utils/codex-realtime-write-guard.ts `
  scripts/acceptance
git diff --cached --stat
git commit -m 'feat(codex): unify enrollment and realtime recovery'
$FrontendSha = (git rev-parse HEAD).Trim()
git push origin main

Write-Host "Backend revision: $BackendSha"
Write-Host "Frontend revision: $FrontendSha"
```

如果 ancestry 检查或 push 因远端前进而失败，停在该处处理真实分叉，不 force push，不重置已有文档改动。重新开终端时可分别用 `git -C <仓库目录> rev-parse HEAD` 恢复上述两个 SHA。

## 3. 等待这两个提交的 CI 镜像

两个仓库 push main 都会自动触发 `production-image.yml`，无需另建镜像。等待的是本次准确 SHA，不能用另一次绿色运行代替。

```powershell
function Wait-ProductionImage([string]$Repository, [string]$Revision) {
  $RunId = ''
  for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    $RunId = gh run list --repo $Repository --workflow production-image.yml `
      --branch main --commit $Revision --limit 1 --json databaseId --jq '.[0].databaseId'
    if ($RunId -and $RunId -ne 'null') { break }
    Start-Sleep -Seconds 2
  }
  if (-not $RunId -or $RunId -eq 'null') { throw "未找到 $Repository 的本次镜像构建。" }
  gh run watch $RunId --repo $Repository --exit-status
}
Wait-ProductionImage $BackendRepo $BackendSha
Wait-ProductionImage $FrontendRepo $FrontendSha
```

## 4. 服务器更新与验证

在 Windows PowerShell 输入已有服务器登录信息：

```powershell
$DeployHost = Read-Host '实际服务器 SSH 地址或 IP'
$DeployUser = Read-Host 'SSH 用户名'
$DeployKey = Read-Host '已有 SSH 私钥的绝对路径'
ssh -i $DeployKey "$DeployUser@$DeployHost"
```

以下改在服务器 **Bash** 执行。已有 `.env.production.local` 继续使用，不运行 bootstrap，不重建密钥。若服务器尚未登录 GHCR，先用现有只读 token 登录；已登录可跳过这段：

```bash
read -r -p 'GHCR username: ' ghcr_user
read -r -s -p 'GHCR read-only token: ' ghcr_token
printf '\n'
printf '%s' "$ghcr_token" | docker login ghcr.io --username "$ghcr_user" --password-stdin
unset ghcr_token
```

统一部署入口按后端→前端→网关顺序启动，自动备份 PostgreSQL、运行迁移并使用镜像 Digest。不要再分别手工 `docker compose up`：

```bash
cd /opt/web/python-web-fastapi || exit 1
export PRODUCTION_FRONTEND_ROOT=/opt/web/typescript-web-nuxt
export COMPOSE_PROFILES=task-worker
unset BACKEND_IMAGE FRONTEND_IMAGE

# 先取得修复后的部署入口；旧入口缺少日志/备份所需的镜像变量初始化。
# 这一步只更新源码，运行中的容器仍由下面的 update 统一切换。
git pull --ff-only origin main || exit 1
bash deploy/production.sh doctor || exit 1
deploy_log="/tmp/codex-deploy-$(date +%Y%m%d-%H%M%S).log"
nohup bash -c '
  set -uo pipefail
  result=0
  bash deploy/production.sh update || result=$?
  if [ "$result" -eq 0 ]; then bash deploy/production.sh status || result=$?; fi
  if [ "$result" -eq 0 ]; then curl --fail --silent --show-error https://nuotop.xyz/health/ready || result=$?; fi
  printf "\nDEPLOY_EXIT_CODE=%s\n" "$result"
  exit "$result"
' >"$deploy_log" 2>&1 < /dev/null &
echo "$deploy_log"
tail -f "$deploy_log"
```

看到 `DEPLOY_EXIT_CODE=0` 后按 Ctrl+C 退出日志跟随，再执行：

```bash
bash deploy/production.sh status
git rev-parse HEAD
git -C "$PRODUCTION_FRONTEND_ROOT" rev-parse HEAD
curl --fail --silent --show-error https://nuotop.xyz/health/live
curl --fail --silent --show-error https://nuotop.xyz/health/ready
docker inspect fastapi-web-production-app-1 --format '{{.Config.Image}}'
docker inspect typescript-web-production-frontend-1 --format '{{.Config.Image}}'
```

核对服务器两个 HEAD 等于第 2 步输出。部署窗口内避免继续推进 main；当前 update 按远端 main 部署，如果 SHA 已变化，需确认新版本对应 CI，不把它当原验收版本。若 SSH 中断，只重新跟随本次打印的日志路径，不再次启动部署。

失败定位沿已有入口：

```bash
bash deploy/production.sh logs backend
bash deploy/production.sh logs frontend
bash deploy/production.sh logs caddy
```

部署成功后告诉本任务，继续实际连接和首次任务验收。本机当前 Agent 已进入协议受阻态，可从“Codex Remote Agent 设置”点“重启”；若使用命令，下面调用的也是同一个产品任务控制器：

```powershell
Set-Location 'E:\python_web_fastapi\work'
@'
import os
from pathlib import Path
from src.infrastructure.codex_agent.windows_agent_task import WindowsAgentTaskController
config = Path(os.environ['LOCALAPPDATA']) / 'CodexRemoteAgent' / 'agent.toml'
print(WindowsAgentTaskController(config_path=config).restart())
'@ | .venv/Scripts/python.exe -
Get-Content -LiteralPath "$env:LOCALAPPDATA\CodexRemoteAgent\runtime-status.json"
```

## 5. 手动发布已验证的 0.1.42

第一轮部署和真实连接验收通过后执行。本路线不运行签名工作流，网站仍以内部包展示；清单保留真实的 `source_dirty=true` 构建来源。

在本机同一个 PowerShell 会话执行：

```powershell
Set-Location 'E:/python_web_fastapi/work'
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$ReleaseVersion = '0.1.42'
$ReleaseRepo = '1nuo123/codex-remote-agent-releases'
$ReleaseRoot = 'E:/python_web_fastapi/codex-remote-agent-releases'
$BuiltRelease = 'E:/python_web_fastapi/.codex-tmp/installer-release/releases/0.1.42'
$ReleaseDirectory = Join-Path $ReleaseRoot "releases/$ReleaseVersion"
$ExpectedMsiSha256 = '1a899d7f8dc801fb41bf57df56224aeba779ac61897150f5d6c2830a4eae3b3d'
$Manifest = Get-Content -LiteralPath "$BuiltRelease/internal-release.json" -Raw | ConvertFrom-Json
$ActualMsiSha256 = (Get-FileHash -LiteralPath "$BuiltRelease/CodexRemoteAgent.msi" -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualMsiSha256 -ne $ExpectedMsiSha256 -or $Manifest.detail.artifact_sha256 -ne $ExpectedMsiSha256) {
  throw 'MSI 与已验收产物不一致。'
}
if ($Manifest.detail.version -ne $ReleaseVersion -or $Manifest.detail.automatic_updates_enabled) {
  throw '清单版本或通道不一致。'
}
if ((git -C $ReleaseRoot branch --show-current) -ne 'master') { throw '发布仓库不是 master。' }
if (git -C $ReleaseRoot diff --cached --name-only) { throw '发布仓库已有暂存内容，请先确认。' }
git -C $ReleaseRoot pull --ff-only origin master
New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
foreach ($Name in @('CodexRemoteAgent.msi', 'internal-release.json', 'SHA256SUMS.json')) {
  $SourceFile = Join-Path $BuiltRelease $Name
  $TargetFile = Join-Path $ReleaseDirectory $Name
  if (Test-Path -LiteralPath $TargetFile) {
    if ((Get-FileHash -LiteralPath $SourceFile).Hash -ne (Get-FileHash -LiteralPath $TargetFile).Hash) {
      throw "现有发布文件不一致，禁止覆盖：$Name"
    }
  } else { Copy-Item -LiteralPath $SourceFile -Destination $TargetFile }
}
git -C $ReleaseRoot add -- "releases/$ReleaseVersion"
git -C $ReleaseRoot diff --cached --stat
git -C $ReleaseRoot commit -m "release: internal Codex Remote Agent $ReleaseVersion"
git -C $ReleaseRoot push origin master
$ReleaseCommit = (git -C $ReleaseRoot rev-parse HEAD).Trim()

$ReleaseNotes = Join-Path $env:TEMP "codex-agent-$ReleaseVersion-notes.md"
@'
Codex Remote Agent 0.1.42 内部体验包。

改进首次连接、原设备恢复、短断连续性及 CLI 版本兼容。
服务地址为 https://nuotop.xyz。
未签名、不启用自动更新；后续版本需手动覆盖安装。
24 小时稳定性验收仍在进行，未计为通过。
'@ | Set-Content -LiteralPath $ReleaseNotes -Encoding utf8
gh release create "v$ReleaseVersion" --repo $ReleaseRepo --target $ReleaseCommit `
  --title "Codex Remote Agent $ReleaseVersion（内部体验）" `
  --notes-file $ReleaseNotes --draft --prerelease `
  "$ReleaseDirectory/CodexRemoteAgent.msi" `
  "$ReleaseDirectory/internal-release.json" `
  "$ReleaseDirectory/SHA256SUMS.json"
gh release view "v$ReleaseVersion" --repo $ReleaseRepo --web
```

核对草稿及三个附件后发布：

```powershell
gh release edit "v$ReleaseVersion" --repo $ReleaseRepo --draft=false --prerelease --latest=false
```

也可在同一个 GitHub 草稿页手动点 Publish release。不要重复创建 tag 或替换已发布资产。本地发布仓库另有历史未跟踪产物，以上只提交本次版本目录。2026-10-20 已将验收后的三个文件复制到该目录，复制步骤会核对已有文件后跳过；若你已完成提交或公开发布，跳过相应已完成步骤。

## 6. 同步下载清单并更新后端仓库

不能只上传 MSI：服务器当前下载配置还指向 0.1.38。以下复用现有同步入口，匿名下载已公开清单与 MSI，核对摘要后再更新配置。最低安全版本保持 0.1.31。

```powershell
Set-Location 'E:/python_web_fastapi/work'
& .venv/Scripts/python.exe -m src.cli.sync_codex_agent_internal_release_metadata `
  --manifest "$ReleaseDirectory/internal-release.json" `
  --config config/runtime/codex_control_runtime/codex_control_runtime_base.toml `
  --config config/runtime/codex_control_runtime/codex_control_runtime_production.toml `
  --minimum-security-version 0.1.31
if (git diff --cached --name-only) { throw '后端已有其他暂存内容，请先确认。' }
git add -- config/runtime/codex_control_runtime/codex_control_runtime_base.toml `
  config/runtime/codex_control_runtime/codex_control_runtime_production.toml
git diff --cached --stat
git commit -m 'release(codex): publish internal Agent 0.1.42 download metadata'
$BackendSha = (git rev-parse HEAD).Trim()
git push origin main
Wait-ProductionImage '1nuo123/python-web-fastapi' $BackendSha
```

`Wait-ProductionImage` 复用第 3 节定义；新开终端时重新定义。前端没有再次改动，不需重复提交。

## 7. 第二次服务器更新及收尾

第一次更新让控制面支持新 Agent；第二次把网站下载切到已公开的 0.1.42。服务器 Bash 使用同一入口：

```bash
cd /opt/web/python-web-fastapi || exit 1
export PRODUCTION_FRONTEND_ROOT=/opt/web/typescript-web-nuxt
export COMPOSE_PROFILES=task-worker
unset BACKEND_IMAGE FRONTEND_IMAGE
bash deploy/production.sh update && bash deploy/production.sh status
curl --fail --silent --show-error https://nuotop.xyz/health/ready
```

SSH 不稳定时复用第 4 节 nohup 方式，只启动一次。登录网站，打开“连接这台电脑”，确认下载版本为 0.1.42、模式为内部体验，地址指向本次 Release。

本机已经安装同一 0.1.42，无需重复卸装。其他电脑用覆盖安装保留原绑定：

```powershell
$DownloadDirectory = Join-Path $env:TEMP 'codex-agent-download-0.1.42'
New-Item -ItemType Directory -Path $DownloadDirectory -Force | Out-Null
$DownloadedMsi = Join-Path $DownloadDirectory 'CodexRemoteAgent.msi'
Invoke-WebRequest `
  -Uri 'https://github.com/1nuo123/codex-remote-agent-releases/releases/download/v0.1.42/CodexRemoteAgent.msi' `
  -OutFile $DownloadedMsi
if ((Get-FileHash -LiteralPath $DownloadedMsi -Algorithm SHA256).Hash.ToLowerInvariant() -ne '1a899d7f8dc801fb41bf57df56224aeba779ac61897150f5d6c2830a4eae3b3d') {
  throw '下载 MSI 与已验收产物不一致。'
}
$InstallLog = Join-Path $DownloadDirectory 'install.log'
$InstallArguments = '/i "' + $DownloadedMsi + '" /qb /norestart /L*v "' + $InstallLog + '"'
$Installer = Start-Process msiexec.exe -ArgumentList $InstallArguments -Wait -PassThru
if ($Installer.ExitCode -notin @(0, 3010)) { throw "安装失败：$($Installer.ExitCode)，日志：$InstallLog" }
```

最终核对原主机、项目、任务输出及刷新历史，不仅以 health/ready 成功结案。若线上仍报 1002，保留服务端日志继续定位，不反复卸载或重新绑定。

服务器回滚仍使用[生产运维指南](../../生产环境Docker一键部署与长期运维指南.md)的已知正常 Digest 入口。正式可信更新机制保留，本次用户选择的手动内部分发不启用它。

