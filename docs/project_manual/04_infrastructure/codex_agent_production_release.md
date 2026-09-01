# Windows Codex Remote Agent 正式发布

本文只描述正式生产发布。开发环境、自签名证书、未配置 bootstrap 和未签名 MSI 均不得发布给外部用户。

## 1. 固定发布边界

- 控制面必须使用一个公网 HTTPS origin；API、WSS Agent 连接、设备验证页和网站入口均从该 origin 固定派生。
- 发布仓库固定为 `1nuo123/codex-remote-agent-releases`，默认分支为 `master`。
- 发布基址固定为 `https://raw.githubusercontent.com/1nuo123/codex-remote-agent-releases/master`。
- EXE 和 MSI 必须由同一受信任 Authenticode 证书签名，并带 RFC 3161 时间戳。
- TUF 必须启用 consistent snapshot；root 和 targets 使用独立 Ed25519 密钥及至少 2-of-N 阈值。
- CI 只能取得 Azure 托管签名权限、已签署的 TUF metadata 和公共发布仓库的最小写权限，不得取得 TUF 私钥。
- `dist/CodexRemoteAgent.msi` 只有在本节所有门禁通过后才能替换。

## 2. 一次性生产准备

### 2.1 Authenticode

在 Azure Key Vault 或等价托管签名服务中配置受信任的组织代码签名证书。GitHub OIDC 主体只授予该证书的签名权限，不授予证书导出、Key Vault 管理或其他密钥权限。

工作流固定安装 .NET 8 运行时和 AzureSignTool 6.0.1。`azure/login` 使用 OIDC 登录后，签名脚本要求 Azure CLI 会话有效，并让 AzureSignTool 通过 `DefaultAzureCredential` 复用该会话；不配置 Azure client secret，也不把短期 access token 放入命令行、artifact、日志或 GitHub Secret。

主仓库 GitHub Secrets：

```text
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
AZURE_KEY_VAULT_URL
AZURE_CERTIFICATE_NAME
```

禁止使用自签名证书作为生产替代，禁止把 `.pfx`、私钥密码或导出的证书私钥放入仓库和普通 CI Secret。

### 2.2 公共发布仓库 token

创建 fine-grained GitHub token：

```text
Repository access: Only selected repositories
Repository: 1nuo123/codex-remote-agent-releases
Repository permissions: Contents = Read and write
```

保存到主仓库 Secret：

```text
CODEX_AGENT_RELEASE_REPOSITORY_TOKEN
```

不得授予 Actions、Administration、Secrets、Members 或其他无关权限。公共仓库应启用分支保护，只允许发布工作流使用的主体推进发布分支，并禁止 force push。

### 2.3 初始化 TUF 信任根

以下命令必须在隔离的离线签名机执行。每把密钥使用不同的高熵口令，口令不得出现在 shell history、仓库、日志或 CI 中。

```powershell
$env:CODEX_TUF_ROOT_KEY_1_PASSWORD = '<independent-secret>'
$env:CODEX_TUF_ROOT_KEY_2_PASSWORD = '<independent-secret>'
$env:CODEX_TUF_ROOT_KEY_3_PASSWORD = '<independent-secret>'
$env:CODEX_TUF_TARGETS_KEY_1_PASSWORD = '<independent-secret>'
$env:CODEX_TUF_TARGETS_KEY_2_PASSWORD = '<independent-secret>'
$env:CODEX_TUF_TARGETS_KEY_3_PASSWORD = '<independent-secret>'
$env:CODEX_TUF_SNAPSHOT_KEY_1_PASSWORD = '<independent-secret>'
$env:CODEX_TUF_TIMESTAMP_KEY_1_PASSWORD = '<independent-secret>'

uv run python -m src.cli.sign_codex_agent_tuf_repository initialize `
  --key-directory D:\CodexAgentTuf\private-keys `
  --trusted-root D:\CodexAgentTuf\public\root.json `
  --root-key-count 3 `
  --root-threshold 2 `
  --targets-key-count 3 `
  --targets-threshold 2
```

初始化结果：

```text
D:\CodexAgentTuf\private-keys\root-1.pem
D:\CodexAgentTuf\private-keys\root-2.pem
D:\CodexAgentTuf\private-keys\root-3.pem
D:\CodexAgentTuf\private-keys\targets-1.pem
D:\CodexAgentTuf\private-keys\targets-2.pem
D:\CodexAgentTuf\private-keys\targets-3.pem
D:\CodexAgentTuf\private-keys\snapshot-1.pem
D:\CodexAgentTuf\private-keys\timestamp-1.pem
D:\CodexAgentTuf\public\root.json
```

所有 PEM 均为加密 PKCS#8。将 root 密钥、targets 密钥和各自口令分开备份到至少两个受控介质；日常发布机不得长期保留 root 私钥。`root.json` 是公开信任材料，可进入 CI Secret 和 MSI。

## 3. 每次 Agent 版本发布

普通 Codex CLI 更新属于运行时能力观测，不要求重建 Agent MSI。Agent 只有在 Remote 源码、配置契约或安装器本身变化时才需要新的 MSI；新 Codex 版本先在隔离 workspace 运行 capability probe，再依据结果进入 `compatible`、`read_only` 或 `blocked`。

### 3.1 生成并签名 EXE

从主仓库手动运行 `Codex Agent Signed Build`，输入：

```text
version: 例如 0.1.3
minimum_security_version: 当前最低安全版本
rollout_percent: 初次建议小比例，验证后逐步扩大
cdn_base_url: https://raw.githubusercontent.com/1nuo123/codex-remote-agent-releases/master
```

工作流必须成功生成 `codex-agent-signed-build-<version>`。下载该 artifact 到离线签名机并保持目录内容不变。

### 3.2 离线签署本次 TUF metadata

首次发布不传 `--previous-metadata-directory`。后续发布必须下载公共仓库当前的 `metadata/timestamp.json`、`metadata/snapshot.json` 和 `metadata/targets.json` 到同一目录，用于单调递增版本并验证旧签名链。

```powershell
uv run python -m src.cli.sign_codex_agent_tuf_repository sign-release `
  --key-directory D:\CodexAgentTuf\release-keys `
  --trusted-root D:\CodexAgentTuf\public\root.json `
  --signed-build-directory D:\CodexAgentRelease\signed-build `
  --output-directory D:\CodexAgentRelease\metadata-0.1.3 `
  --version 0.1.3 `
  --previous-metadata-directory D:\CodexAgentRelease\previous-metadata
```

`release-keys` 只装载满足 targets 阈值的授权密钥，以及 snapshot、timestamp 密钥；不需要 root 私钥。命令会验证精确 EXE、发布清单、build record、TUF 签名链和发布基址，失败时不会保留输出目录。

输出目录必须只包含：

```text
targets.json
snapshot.json
timestamp.json
tuf-metadata.zip
```

### 3.3 更新 CI 的公开信任材料

PowerShell 7 生成单行 Base64：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('D:\CodexAgentTuf\public\root.json')) |
  gh secret set TUF_TRUSTED_ROOT_BASE64 --repo 1nuo123/python-web-fastapi

[Convert]::ToBase64String([IO.File]::ReadAllBytes('D:\CodexAgentRelease\metadata-0.1.3\tuf-metadata.zip')) |
  gh secret set TUF_SIGNED_METADATA_ZIP_BASE64 --repo 1nuo123/python-web-fastapi
```

不要输出 Base64 内容，不要写入临时文本文件。发布完成后立即用下一次发布所需的受控流程轮换或删除一次性 metadata Secret。

### 3.4 验证、构建 MSI 并原子发布

手动运行 `Codex Agent Verified Publish`：

```text
signed_build_run_id: 上一步成功的 Signed Build run ID
version: 与 signed build 和 TUF metadata 完全一致
public_origin: https://<public-host>[:port]
expected_codex_version: 0.145.0
app_server_schema_digest: 当前审核的 64 位 SHA-256
release_repository: 1nuo123/codex-remote-agent-releases
release_repository_branch: master
release_base_url: https://raw.githubusercontent.com/1nuo123/codex-remote-agent-releases/master
```

工作流只接受不含路径、query、fragment 或凭据的 `public_origin`，并固定派生：

```text
api_url: <public_origin>
websocket_url: wss://<public-host>[:port]/internal/codex-agents/connect
verification_url: <public_origin>/codex/verify-device
website_url: <public_origin>
```

四个入口必须使用同一主机和端口；任一路径或 origin 不匹配时，Bootstrap 校验会在构建 MSI 前终止发布。

工作流按顺序执行：

1. 锁定成功 Signed Build 的源 revision。
2. 校验 TUF root、timestamp、snapshot、targets 与精确签名 EXE/manifest/build record。
3. 生成带公网 bootstrap 和 TUF root 的 per-user x64 MSI。
4. 使用与 EXE 相同的托管证书签名 MSI，并核对 signer SHA-256。
5. 构造 consistent-snapshot 目标、版本化元数据、稳定下载文件和 `SHA256SUMS.json`。
6. 对公共发布仓库只创建一个 Git commit，再一次 push 推进全部发布文件。

任一检查失败时不得手工复制 MSI、修改 metadata 或跳过签名重新发布。

## 4. 发布后验证

下载公共仓库中的正式 MSI，不使用工作流本地副本：

```powershell
$msi = "$env:TEMP\CodexRemoteAgent.msi"
Invoke-WebRequest `
  -Uri 'https://raw.githubusercontent.com/1nuo123/codex-remote-agent-releases/master/CodexRemoteAgent.msi' `
  -OutFile $msi
Get-AuthenticodeSignature -LiteralPath $msi | Format-List Status,SignerCertificate
```

必须在 clean Windows 普通用户环境完成：

1. 首次安装成功，无管理员权限提示。
2. 同版本再次运行进入 Windows Installer 维护/修复语义，不创建第二份程序、任务或注册表入口。
3. `%LOCALAPPDATA%\CodexRemoteAgent` 只有一个安装根；计划任务名包含当前用户 SID，运行级别为 Limited，`MultipleInstances=IgnoreNew`。
4. 打开设备验证页，已有在线主机时显示已连接状态；重新下载安装包只替换安装包下载行为，不重复注册主机。
5. Agent 完成设备批准、Codex 登录/doctor、工作区选择并通过 WSS 上线。
6. 从网站创建任务并收到最终响应；刷新后 thread 历史仍可恢复。
7. 新版本 MSI 完成 major upgrade，保留配置、DPAPI 密钥、状态和工作区；旧版本 downgrade 被拒绝。
8. 卸载后计划任务、URI scheme、快捷方式、安装文件、配置、DPAPI 密钥、SQLite、日志、staging/release 目录和 HKCU 组件键全部移除。

发布证据至少保存 MSI/EXE SHA-256、Authenticode 状态与证书指纹、TUF metadata 版本、Git 发布 commit、安装/重复安装/升级/卸载退出码和浏览器任务 ID。不得保存设备私钥、一次性 code、token 或用户 prompt 正文。

## 5. 紧急停止与回滚

- 坏版本尚未扩大：停止 rollout，生成更高 metadata 版本指向最近已知正常版本；不得回退 TUF metadata 版本。
- 已达到最低安全版本封禁条件：提高 `minimum_security_version`，但必须保证仍存在一条可安装的安全升级路径。
- 证书失陷：立即停止发布，撤销证书，轮换 Authenticode signer allowlist，并发布由新证书签名的 MSI/EXE；不得继续接受旧失陷 signer。
- targets 密钥失陷：使用仍满足 root 阈值的 root 密钥轮换 targets 角色并提升 root 版本；客户端先取得新 root，再接受新 targets。
- root 密钥不足阈值或全部丢失：现有客户端无法安全建立新信任根。不得伪造恢复；必须按灾难恢复策略重新分发可信安装介质。

所有回滚仍需使用更高的 timestamp、snapshot 和 targets 版本，保留 consistent snapshot 与 Authenticode 双重验证。

## 6. 2026-08-15 Agent 0.1.10 本地验收记录

### 6.1 产物与签名边界

本地验收产物：

```text
Agent version: 0.1.10
EXE version: 0.1.10.0
MSI: E:\python_web_fastapi\work\dist\CodexRemoteAgent.msi
Build directory: E:\python_web_fastapi\work\.codex-tmp\local-agent-acceptance-local-0.1.10
Lifecycle evidence: E:\python_web_fastapi\work\.codex-tmp\lifecycle-0.1.10
```

摘要：

```text
MSI SHA-256: 068c5351fbd0c32b01ee7f46b035b235e3c9ea800a53fbf956aa9205017c94f3
EXE SHA-256: f85c59202cb48c661ddc78176a2a84ab47bcdda1c56d22d23d6f91002aa4d77e
```

本地证书主题为 `CN=Codex Remote Agent Local Acceptance Only`，验收时 Authenticode 状态为
`UnknownError`。该证书为自签名证书，产物只能用于本机生命周期验证，不满足本文件第 1 节的正式发布边界，
不得上传公共发布仓库或提供给外部用户。

### 6.2 生命周期结果

| 场景 | 退出码 | 结果 |
|---|---:|---|
| `0.1.9 → 0.1.10` 升级 | `0` | 成功，保留配置与 DPAPI 设备密钥 |
| 同版本安装 | `0` | 进入维护语义，未创建第二个 Agent |
| `0.1.10 → 0.1.9` 降级 | `1603` | 按版本策略拒绝 |
| 卸载 | `0` | 成功 |
| 重装 | `0` | 成功，最终版本 `0.1.10.0` |

最终计划任务状态为 `Running`，Agent 在线。进程树只有 PyInstaller 父子两个
`codex-remote-agent.exe` 进程，二者属于一个逻辑 Agent，没有额外 launcher worker。

### 6.3 稳定入口与无窗口策略

当所选 Agent 是当前 MSI 内置可执行文件时，稳定入口在当前进程执行 `launch run` 转发，不再启动长期
子进程。只有已验证的在线更新版本才使用外部进程，并将 `timeout_seconds` 设为 `None`，使超时语义跟随
完整 Agent 生命周期。

PowerShell、Git、Node、Codex、计划任务控制和 App Server 进程统一使用
`WindowsSubprocessLauncher`，固定 `shell=False`、隐藏 startup info 与 `CREATE_NO_WINDOW`；安装、升级、
同版本维护、降级拒绝、卸载、重装和计划任务运行期间未产生可见命令行窗口。

### 6.4 正式发布前剩余门禁

本地验收不替代以下正式门禁：受信任组织 Authenticode 证书、RFC 3161 时间戳、TUF metadata、公共发布
commit、clean Windows/Defender/SmartScreen 验证和外部下载后的签名复验。只有第 1 至第 4 节全部通过，
才允许将 `dist/CodexRemoteAgent.msi` 作为正式发布包。

## 7. 内部体验发布通道

本节是正式发布前、面向已知朋友的最小可用通道。它与第 1 至第 5 节的正式发布完全分离，不能把未签名
内部包表述为正式版本：内部包没有 Authenticode、TUF 或自动更新，但必须使用生产 profile、HTTPS/WSS、
独立设备授权和不可变版本地址。

### 7.1 固定边界

- 每位使用者注册自己的普通账号并授予所需 Codex scope；不得共用 `nuo` 或管理员账号。
- 包内只能包含 `https://nuotop.xyz`、`wss://nuotop.xyz/internal/codex-agents/connect` 和
  `https://nuotop.xyz/codex/verify-device`。不得包含开发 CA、`codex-dev.lan`、TUF root、更新源、服务器密码、JWT、Deploy Key 或设备私钥。
- 发布版本使用新的三段版本号，且同一版本的 MSI、清单和校验文件一旦生成不得覆盖。
- 外部下载使用 GitHub Release 的精确 tag 资产地址，禁止 `master`、`main`、`latest` 或其他可变地址。
- 下载页必须展示内部体验警告、SHA-256 和确认框；确认后仅下载，不绕过后续设备授权。

### 7.2 构建与本地校验

在 `E:\python_web_fastapi\work` 的 Windows PowerShell 中为新版本执行。以下示例为已经构建的 `0.1.16`；重发时必须先改成未使用的新版本号。

```powershell
& .\scripts\codex\build_internal_production_agent_installer.ps1 `
  -PublicOrigin 'https://nuotop.xyz' `
  -ReleaseRepositoryRoot 'E:\python_web_fastapi\codex-remote-agent-releases' `
  -Version '0.1.16' `
  -DownloadUrl 'https://github.com/1nuo123/codex-remote-agent-releases/releases/download/v0.1.16/CodexRemoteAgent.msi'

Get-FileHash `
  'E:\python_web_fastapi\codex-remote-agent-releases\releases\0.1.16\CodexRemoteAgent.msi' `
  -Algorithm SHA256
```

构建会生成并相互绑定以下三个文件：

```text
releases/<version>/CodexRemoteAgent.msi
releases/<version>/internal-release.json
releases/<version>/SHA256SUMS.json
```

`internal-release.json` 必须声明 `automatic_updates_enabled: false`，其 MSI 摘要必须与 `SHA256SUMS.json` 和
生产运行时配置完全一致。发布前可运行：

```powershell
& .\.tools\wix.exe msi validate '.\dist\internal-releases\0.1.16\CodexRemoteAgent.msi'
uv run pytest -q test/unit_test/test_codex_agent_internal_release_manifest_unit.py test/unit_test/test_codex_agent_release_manifest_unit.py test/initialization_test/test_codex_settings_initialization.py test/interface_test/test_codex_admin_enrollment_interface.py
```

### 7.3 对外发布和生产配置顺序

1. 审核 `releases/<version>` 的三个文件，仅提交该版本目录；不要提交私钥、临时 payload、`dist` 中的其他安装包或历史未确认修改。
2. 创建 GitHub Release `v<version>`，上传 `CodexRemoteAgent.msi`、`internal-release.json` 和 `SHA256SUMS.json`。发布前保持草稿；公开后通过浏览器或 `Invoke-WebRequest` 从 Release URL 下载 MSI，再次计算 SHA-256。
3. 将下载 URL、清单 URL、版本和 SHA-256 写入后端的 `config/runtime/codex_control_runtime/codex_control_runtime_production.toml`。内部模式必须为 `internal`，最低安全版本不得高于当前版本。
4. 先部署后端配置，再部署前端。仅在生产 API 的 `/codex/agent-release/current` 已返回上述精确版本、内部模式和 SHA-256 后，将生产前端的 `NUXT_PUBLIC_CODEX_FEATURE_ENABLED` 设为 `true` 并重新部署。
5. 使用无管理员权限的干净 Windows 普通用户账号，从生产下载页确认警告后下载并核验 SHA-256，安装 MSI，完成该用户自己的设备授权。随后验证上线、添加工作区、发送/接收消息、审批、暂停和重启；每个操作均以该用户自己的 Codex 权限运行。

任何一步失败时关闭 `NUXT_PUBLIC_CODEX_FEATURE_ENABLED`，保留旧的已验证版本，不复用或覆盖已发布版本号。内部通道没有自动更新，因此修复版本必须由使用者重新下载、核验并执行 MSI 升级；正式签名/TUF 发布完成后再切换到第 1 至第 5 节的正式通道。
