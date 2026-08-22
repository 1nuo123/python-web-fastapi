[CmdletBinding()]
param(
  [string]$DevelopmentOrigin = "https://codex-dev.lan",
  [string]$DevelopmentCaCertificatePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$distRoot = Join-Path $repositoryRoot "dist"
$runtimeSettingsPath = Join-Path $repositoryRoot "config\runtime\codex_control_runtime\codex_control_runtime_base.toml"
$schemaManifestPath = Join-Path $repositoryRoot "protocol\codex_app_server\0.145.0\manifest.json"
$agentVersionPattern = '(?m)^agent_release_version\s*=\s*"(?<version>\d+\.\d+\.\d+)"\s*$'
$runtimeSettings = Get-Content -LiteralPath $runtimeSettingsPath -Raw -Encoding UTF8

if ($runtimeSettings -notmatch $agentVersionPattern) {
  throw "Unable to read the Agent release version from runtime settings."
}
$agentVersion = $Matches.version
$schemaManifest = Get-Content -LiteralPath $schemaManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$codexVersion = [string]$schemaManifest.header.codex_version
$schemaDigest = [string]$schemaManifest.detail.json_schema_bundle_sha256

if ([string]::IsNullOrWhiteSpace($DevelopmentCaCertificatePath)) {
  $DevelopmentCaCertificatePath = Join-Path $repositoryRoot "artifacts\codex-dev-root-ca.crt"
}
if (-not (Test-Path -LiteralPath $DevelopmentCaCertificatePath -PathType Leaf)) {
  throw "Development MSI requires the Caddy CA certificate: $DevelopmentCaCertificatePath"
}

$developmentCaPath = (Resolve-Path -LiteralPath $DevelopmentCaCertificatePath).Path
$payloadRoot = Join-Path $distRoot "installer-payload-development"
$identityPath = Join-Path $distRoot "windows-installer-identity-development.json"
$installerPath = Join-Path $distRoot "CodexRemoteAgent.msi"
$versionInfoPath = Join-Path $repositoryRoot ".build\windows-agent-version-info.txt"
$wixToolDirectory = Join-Path $repositoryRoot ".tools"
$wixExecutable = Join-Path $wixToolDirectory "wix.exe"

Push-Location $repositoryRoot
try {
  New-Item -ItemType Directory -Force $distRoot | Out-Null
  New-Item -ItemType Directory -Force $payloadRoot | Out-Null
  New-Item -ItemType Directory -Force $wixToolDirectory | Out-Null

  & uv run python -m src.cli.build_codex_agent_windows_version_info `
    --version $agentVersion `
    --output $versionInfoPath
  if ($LASTEXITCODE -ne 0) {
    throw "Agent Windows version resource generation failed."
  }

  $env:CODEX_AGENT_VERSION_FILE = $versionInfoPath
  & uv run pyinstaller --clean --noconfirm packaging/windows/agent.spec
  if ($LASTEXITCODE -ne 0) {
    throw "Development Agent executable build failed."
  }

  Copy-Item -LiteralPath (Join-Path $distRoot "codex-remote-agent.exe") -Destination (Join-Path $payloadRoot "codex-remote-agent.exe") -Force
  Copy-Item -LiteralPath (Join-Path $repositoryRoot "packaging\windows\scripts\register_task_scheduler.ps1") -Destination $payloadRoot -Force
  Copy-Item -LiteralPath (Join-Path $repositoryRoot "packaging\windows\scripts\unregister_task_scheduler.ps1") -Destination $payloadRoot -Force
  Copy-Item -LiteralPath (Join-Path $repositoryRoot "packaging\windows\scripts\purge_agent_state.ps1") -Destination $payloadRoot -Force
  Copy-Item -LiteralPath $developmentCaPath -Destination (Join-Path $payloadRoot "codex-dev-root-ca.crt") -Force

  & uv run python -m src.cli.build_codex_agent_bootstrap `
    --output (Join-Path $payloadRoot "agent-bootstrap.toml") `
    --development-origin $DevelopmentOrigin `
    --agent-version $agentVersion `
    --expected-codex-version $codexVersion `
    --app-server-schema-digest $schemaDigest
  if ($LASTEXITCODE -ne 0) {
    throw "Development Agent bootstrap generation failed."
  }

  & uv run python -m src.cli.build_codex_agent_installer_identity `
    --version $agentVersion `
    --deployment-profile development `
    --output $identityPath
  if ($LASTEXITCODE -ne 0) {
    throw "Development MSI identity generation failed."
  }

  if (-not (Test-Path -LiteralPath $wixExecutable -PathType Leaf)) {
    & dotnet tool install wix --tool-path $wixToolDirectory --version 6.0.2
    if ($LASTEXITCODE -ne 0) {
      throw "WiX tool installation failed."
    }
  }

  $installerIdentity = Get-Content -LiteralPath $identityPath -Raw -Encoding UTF8 | ConvertFrom-Json
  & $wixExecutable build "packaging/windows/wix/Product.wxs" `
    -arch x64 `
    -d AgentSource=$payloadRoot `
    -d ProductVersion=$agentVersion `
    -d "ProductCode=$($installerIdentity.product_code)" `
    -d "UpgradeCode=$($installerIdentity.upgrade_code)" `
    -d DeploymentProfile=development `
    -d IncludeTrustedRoot=0 `
    -o $installerPath
  if ($LASTEXITCODE -ne 0) {
    throw "Development MSI build failed."
  }

  Write-Output "Development MSI generated: $installerPath"
}
finally {
  Remove-Item Env:CODEX_AGENT_VERSION_FILE -ErrorAction SilentlyContinue
  Pop-Location
}
