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
$schemaDigest = "86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109"
$codexVersion = "0.145.0"

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
