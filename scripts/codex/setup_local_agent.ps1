param(
    [ValidateSet("production", "development")][string]$DeploymentProfile = "development",
    [string]$ApiUrl = "https://codex-dev.lan",
    [string]$WebsocketUrl = "wss://codex-dev.lan/internal/codex-agents/connect",
    [string]$VerificationUrl = "https://codex-dev.lan/codex/verify-device",
    [string]$CodexBinary = "codex",
    [string]$DevelopmentCaCertificatePath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$productionStateDirectory = Join-Path $env:LOCALAPPDATA "CodexRemoteAgent"
$stateDirectory = if ($DeploymentProfile -eq "development") {
    Join-Path $productionStateDirectory "Development"
} else {
    $productionStateDirectory
}
$configPath = Join-Path $stateDirectory "agent.toml"
$workspaceRoot = $repositoryRoot
$codexVersionOutput = & $CodexBinary --version 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($codexVersionOutput)) {
    throw "无法读取本机 Codex CLI 版本，请先安装或修复 Codex。"
}
$codexVersion = ($codexVersionOutput -split '\s+')[-1].Trim()
$schemaDigest = ""
$manifestPath = Join-Path $repositoryRoot ("protocol\codex_app_server\{0}\manifest.json" -f $codexVersion)
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $schemaDigest = [string]$manifest.detail.json_schema_bundle_sha256
}

if ($DeploymentProfile -eq "development") {
    if ([string]::IsNullOrWhiteSpace($DevelopmentCaCertificatePath)) {
        $DevelopmentCaCertificatePath = Join-Path $repositoryRoot "artifacts\codex-dev-root-ca.crt"
    }
    if (-not (Test-Path -LiteralPath $DevelopmentCaCertificatePath -PathType Leaf)) {
        throw "开发 Agent 需要已导出的 Caddy CA 证书：$DevelopmentCaCertificatePath"
    }
    $DevelopmentCaCertificatePath = (Resolve-Path -LiteralPath $DevelopmentCaCertificatePath).Path
}

Push-Location $repositoryRoot
try {
    $agentSetupArguments = @(
        "--deployment-profile", $DeploymentProfile,
        "--config", $configPath,
        "setup",
        "--api-url", $ApiUrl,
        "--websocket-url", $WebsocketUrl,
        "--verification-url", $VerificationUrl,
        "--display-name", $env:COMPUTERNAME,
        "--workspace-root", $workspaceRoot,
        "--workspace-key", "fastapi-work",
        "--workspace-name", "FastAPI Backend",
        "--codex-version", $codexVersion,
        "--codex-binary", $CodexBinary,
        "--schema-digest", $schemaDigest
    )
    if ($DeploymentProfile -eq "development") {
        $agentSetupArguments += @(
            "--development-ca-certificate-path",
            $DevelopmentCaCertificatePath
        )
    }
    & uv run python -m src.cli.run_codex_host_agent @agentSetupArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Agent 设备授权失败，退出码：$LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
