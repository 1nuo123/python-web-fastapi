$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$configPath = Join-Path $env:LOCALAPPDATA "CodexRemoteAgent\agent.toml"
$workspaceRoot = $repositoryRoot
$schemaDigest = "86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109"
$codexVersion = "0.145.0"
$apiUrl = "http://127.0.0.1:8000"
$websocketUrl = "ws://127.0.0.1:8000/internal/codex-agents/connect"
$verificationUrl = "http://127.0.0.1:3000/codex/verify-device"

Push-Location $repositoryRoot
try {
    & uv run python -m src.cli.run_codex_host_agent `
        --config $configPath `
        setup `
        --api-url $apiUrl `
        --websocket-url $websocketUrl `
        --verification-url $verificationUrl `
        --display-name $env:COMPUTERNAME `
        --workspace-root $workspaceRoot `
        --workspace-key "fastapi-work" `
        --workspace-name "FastAPI Backend" `
        --codex-version $codexVersion `
        --schema-digest $schemaDigest
    if ($LASTEXITCODE -ne 0) {
        throw "Agent 设备授权失败，退出码：$LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
