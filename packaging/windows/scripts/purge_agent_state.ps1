[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$InstallRoot,
  [ValidateSet("production", "development")][string]$DeploymentProfile = "production"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$resolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$productionRoot = [IO.Path]::GetFullPath(
  (Join-Path $env:LOCALAPPDATA "CodexRemoteAgent")
).TrimEnd('\')
$expectedRoot = if ($DeploymentProfile -eq "development") {
  [IO.Path]::GetFullPath((Join-Path $productionRoot "Development")).TrimEnd('\')
} else {
  $productionRoot
}
if (-not $resolvedInstallRoot.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing to purge a non-standard Agent data directory."
}
if ($resolvedInstallRoot.Length -le ([IO.Path]::GetPathRoot($resolvedInstallRoot)).Length) {
  throw "Refusing to purge a filesystem root."
}

$packageFiles = [Collections.Generic.HashSet[string]]::new(
  [StringComparer]::OrdinalIgnoreCase
)
foreach ($fileName in @(
    "codex-remote-agent.exe",
    "agent-bootstrap.toml",
    "codex-dev-root-ca.crt",
    "register_task_scheduler.ps1",
    "unregister_task_scheduler.ps1",
    "purge_agent_state.ps1",
    "root.json"
  )) {
  [void]$packageFiles.Add($fileName)
}

$expectedPrefix = $resolvedInstallRoot + [IO.Path]::DirectorySeparatorChar
foreach ($item in Get-ChildItem -LiteralPath $resolvedInstallRoot -Force) {
  if ($packageFiles.Contains($item.Name)) {
    continue
  }
  $path = [IO.Path]::GetFullPath($item.FullName)
  if (-not $path.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to purge data outside the Agent installation directory."
  }
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    Remove-Item -LiteralPath $path -Force -ErrorAction Stop
    continue
  }
  Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
}
