[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [ValidatePattern('^https://[^/?#]+$')]
  [string]$PublicOrigin,

  [Parameter(Mandatory)]
  [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })]
  [string]$ReleaseRepositoryRoot,

  [Parameter(Mandatory)]
  [ValidatePattern('^\d+\.\d+\.\d+$')]
  [string]$Version,

  [Parameter(Mandatory)]
  [ValidatePattern('^https://[^?#]+$')]
  [string]$DownloadUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$releaseRepository = (Resolve-Path -LiteralPath $ReleaseRepositoryRoot).Path
$schemaManifestPath = Join-Path $repositoryRoot "protocol\codex_app_server\0.145.0\manifest.json"
$distRoot = Join-Path $repositoryRoot "dist"
$payloadRoot = Join-Path $distRoot "installer-payload-internal-$Version"
$identityPath = Join-Path $distRoot "windows-installer-identity-internal-$Version.json"
$localReleaseRoot = Join-Path $distRoot "internal-releases\$Version"
$localInstallerPath = Join-Path $localReleaseRoot "CodexRemoteAgent.msi"
$releaseRoot = Join-Path $releaseRepository "releases\$Version"
$releaseInstallerPath = Join-Path $releaseRoot "CodexRemoteAgent.msi"
$releaseManifestPath = Join-Path $releaseRoot "internal-release.json"
$releaseChecksumsPath = Join-Path $releaseRoot "SHA256SUMS.json"
$versionInfoPath = Join-Path $repositoryRoot ".build\windows-agent-version-info-$Version.txt"
$wixToolDirectory = Join-Path $repositoryRoot ".tools"
$wixExecutable = Join-Path $wixToolDirectory "wix.exe"

foreach ($immutablePath in @($releaseInstallerPath, $releaseManifestPath, $releaseChecksumsPath)) {
  if (Test-Path -LiteralPath $immutablePath) {
    throw "Internal release version $Version already has an immutable artifact: $immutablePath"
  }
}

$schemaManifest = Get-Content -LiteralPath $schemaManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$codexVersion = [string]$schemaManifest.header.codex_version
$schemaDigest = [string]$schemaManifest.detail.json_schema_bundle_sha256

Push-Location $repositoryRoot
try {
  New-Item -ItemType Directory -Force $distRoot | Out-Null
  New-Item -ItemType Directory -Force $payloadRoot | Out-Null
  New-Item -ItemType Directory -Force $localReleaseRoot | Out-Null
  New-Item -ItemType Directory -Force $wixToolDirectory | Out-Null
  New-Item -ItemType Directory -Force $releaseRoot | Out-Null

  & uv run python -m src.cli.build_codex_agent_windows_version_info `
    --version $Version `
    --output $versionInfoPath
  if ($LASTEXITCODE -ne 0) {
    throw "Internal Agent Windows version resource generation failed."
  }

  $env:CODEX_AGENT_VERSION_FILE = $versionInfoPath
  & uv run pyinstaller --clean --noconfirm packaging/windows/agent.spec
  if ($LASTEXITCODE -ne 0) {
    throw "Internal Agent executable build failed."
  }

  Copy-Item -LiteralPath (Join-Path $distRoot "codex-remote-agent.exe") -Destination (Join-Path $payloadRoot "codex-remote-agent.exe") -Force
  Copy-Item -LiteralPath (Join-Path $repositoryRoot "packaging\windows\scripts\register_task_scheduler.ps1") -Destination $payloadRoot -Force
  Copy-Item -LiteralPath (Join-Path $repositoryRoot "packaging\windows\scripts\unregister_task_scheduler.ps1") -Destination $payloadRoot -Force
  Copy-Item -LiteralPath (Join-Path $repositoryRoot "packaging\windows\scripts\purge_agent_state.ps1") -Destination $payloadRoot -Force

  & uv run python -m src.cli.build_codex_agent_bootstrap `
    --output (Join-Path $payloadRoot "agent-bootstrap.toml") `
    --public-origin $PublicOrigin `
    --agent-version $Version `
    --expected-codex-version $codexVersion `
    --app-server-schema-digest $schemaDigest
  if ($LASTEXITCODE -ne 0) {
    throw "Internal Agent bootstrap generation failed."
  }

  $bootstrapContent = Get-Content -LiteralPath (Join-Path $payloadRoot "agent-bootstrap.toml") -Raw -Encoding UTF8
  foreach ($requiredValue in @($PublicOrigin, "wss://$($PublicOrigin.Substring(8))/internal/codex-agents/connect", "$PublicOrigin/codex/verify-device")) {
    if (-not $bootstrapContent.Contains($requiredValue)) {
      throw "Internal Agent bootstrap does not contain the required production endpoint."
    }
  }
  if ($bootstrapContent.Contains("[release]") -or $bootstrapContent.Contains("codex-dev.lan") -or $bootstrapContent.Contains("root.json")) {
    throw "Internal Agent bootstrap must not include auto-update, development, or TUF settings."
  }

  & uv run python -m src.cli.build_codex_agent_installer_identity `
    --version $Version `
    --deployment-profile production `
    --output $identityPath
  if ($LASTEXITCODE -ne 0) {
    throw "Internal Agent MSI identity generation failed."
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
    -d ProductVersion=$Version `
    -d "ProductCode=$($installerIdentity.product_code)" `
    -d "UpgradeCode=$($installerIdentity.upgrade_code)" `
    -d DeploymentProfile=production `
    -d IncludeTrustedRoot=0 `
    -o $localInstallerPath
  if ($LASTEXITCODE -ne 0) {
    throw "Internal Agent MSI build failed."
  }

  Copy-Item -LiteralPath $localInstallerPath -Destination $releaseInstallerPath
  & uv run python -m src.cli.build_codex_agent_internal_release_manifest `
    --installer $releaseInstallerPath `
    --output $releaseManifestPath `
    --version $Version `
    --download-url $DownloadUrl
  if ($LASTEXITCODE -ne 0) {
    throw "Internal Agent release manifest generation failed."
  }

  $manifest = Get-Content -LiteralPath $releaseManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $installerDigest = (Get-FileHash -LiteralPath $releaseInstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($manifest.detail.artifact_sha256 -ne $installerDigest -or $manifest.detail.automatic_updates_enabled) {
    throw "Internal Agent release manifest does not match the generated MSI boundary."
  }
  [ordered]@{
    "CodexRemoteAgent.msi" = $installerDigest
    "internal-release.json" = (Get-FileHash -LiteralPath $releaseManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
  } | ConvertTo-Json | Set-Content -LiteralPath $releaseChecksumsPath -Encoding UTF8 -NoNewline

  Write-Output "Internal production MSI generated: $releaseInstallerPath"
  Write-Output "SHA-256: $installerDigest"
}
finally {
  Remove-Item Env:CODEX_AGENT_VERSION_FILE -ErrorAction SilentlyContinue
  Pop-Location
}
