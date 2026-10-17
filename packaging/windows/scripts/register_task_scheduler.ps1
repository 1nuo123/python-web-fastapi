[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$InstallRoot,
  [ValidateSet("production", "development")][string]$DeploymentProfile = "production"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$resolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$resolvedExecutablePath = [IO.Path]::GetFullPath(
  (Join-Path $resolvedInstallRoot "codex-remote-agent.exe")
)
$resolvedBootstrapPath = [IO.Path]::GetFullPath(
  (Join-Path $resolvedInstallRoot "agent-bootstrap.toml")
)
$expectedPrefix = $resolvedInstallRoot + [IO.Path]::DirectorySeparatorChar
foreach ($path in @($resolvedExecutablePath, $resolvedBootstrapPath)) {
  if (-not $path.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Scheduled-task files must stay inside the Agent installation directory."
  }
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Required scheduled-task file does not exist: $path"
  }
}

$currentIdentity = (& "$env:SystemRoot\System32\whoami.exe" /user /fo csv /nh) |
  ConvertFrom-Csv -Header UserName, Sid
$currentUser = [string]$currentIdentity.UserName
$currentUserSid = [string]$currentIdentity.Sid
if ([string]::IsNullOrWhiteSpace($currentUser) -or
    $currentUserSid -notmatch '^S-1-(?:\d+-)+\d+$') {
  throw "Unable to resolve the current Windows user and SID."
}
$profileTaskSuffix = if ($DeploymentProfile -eq "development") { "-Development" } else { "" }
$taskName = "CodexRemoteAgent$profileTaskSuffix-$currentUserSid"
if ($DeploymentProfile -eq "production") {
  $legacyTask = Get-ScheduledTask -TaskName "CodexRemoteAgent" -ErrorAction SilentlyContinue
  if ($null -ne $legacyTask -and
      ($legacyTask.Principal.UserId -ieq $currentUser -or
       $legacyTask.Principal.UserId -ieq $currentUserSid)) {
    Stop-ScheduledTask -TaskName "CodexRemoteAgent" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "CodexRemoteAgent" -Confirm:$false
  }
}
$configPath = Join-Path $resolvedInstallRoot "agent.toml"
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$shouldStart = (Test-Path -LiteralPath $configPath -PathType Leaf) -and (
  $null -eq $existingTask -or $existingTask.Settings.Enabled
)
$arguments = @()
if ($DeploymentProfile -eq "development") {
  $arguments += "--deployment-profile", "development"
}
$arguments += @(
  "--config", ('"{0}"' -f $configPath),
  "--bootstrap", ('"{0}"' -f $resolvedBootstrapPath),
  "launch", "run"
)
$arguments = $arguments -join " "
$action = New-ScheduledTaskAction `
  -Execute $resolvedExecutablePath `
  -Argument $arguments `
  -WorkingDirectory $resolvedInstallRoot
$recoveryInterval = New-TimeSpan -Minutes 1
$triggers = @(
  (New-ScheduledTaskTrigger -AtLogOn -User $currentUser),
  (New-ScheduledTaskTrigger -Once -At (Get-Date).Add($recoveryInterval) -RepetitionInterval $recoveryInterval)
)
$principal = New-ScheduledTaskPrincipal `
  -UserId $currentUser `
  -LogonType Interactive `
  -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -MultipleInstances IgnoreNew `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries
Register-ScheduledTask `
  -TaskName $taskName `
  -Action $action `
  -Trigger $triggers `
  -Principal $principal `
  -Settings $settings `
  -Force | Out-Null
# IgnoreNew preserves a live Agent; the next OS trigger recovers an exited instance.
# Disabled is the sole pause authority, including installations not yet bound.
if ($shouldStart) {
  Start-ScheduledTask -TaskName $taskName
} else {
  Disable-ScheduledTask -TaskName $taskName | Out-Null
}
