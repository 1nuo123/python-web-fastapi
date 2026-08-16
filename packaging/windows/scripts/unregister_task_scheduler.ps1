[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$InstallRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$resolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$expectedPrefix = $resolvedInstallRoot + [IO.Path]::DirectorySeparatorChar

$currentIdentity = (& "$env:SystemRoot\System32\whoami.exe" /user /fo csv /nh) |
  ConvertFrom-Csv -Header UserName, Sid
$currentUser = [string]$currentIdentity.UserName
$currentUserSid = [string]$currentIdentity.Sid
if ([string]::IsNullOrWhiteSpace($currentUser) -or
    $currentUserSid -notmatch '^S-1-(?:\d+-)+\d+$') {
  throw "Unable to resolve the current Windows user and SID."
}
$taskNames = @("CodexRemoteAgent-$currentUserSid", "CodexRemoteAgent")
foreach ($taskName in $taskNames) {
  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($null -eq $task) {
    continue
  }
  if ($taskName -eq "CodexRemoteAgent" -and
      $task.Principal.UserId -ine $currentUser -and
      $task.Principal.UserId -ine $currentUserSid) {
    continue
  }
  Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$agentProcesses = @(
  Get-CimInstance -ClassName Win32_Process -Filter "Name = 'codex-remote-agent.exe'" |
    Where-Object {
      -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
      [IO.Path]::GetFullPath([string]$_.ExecutablePath).StartsWith(
        $expectedPrefix,
        [StringComparison]::OrdinalIgnoreCase
      )
    }
)
if ($agentProcesses.Count -eq 0) {
  exit 0
}

$allProcesses = @(Get-CimInstance -ClassName Win32_Process)
$pendingParentIds = [Collections.Generic.Queue[uint32]]::new()
$processIds = [Collections.Generic.HashSet[uint32]]::new()
foreach ($process in $agentProcesses) {
  $processId = [uint32]$process.ProcessId
  [void]$processIds.Add($processId)
  $pendingParentIds.Enqueue($processId)
}
while ($pendingParentIds.Count -gt 0) {
  $parentId = $pendingParentIds.Dequeue()
  foreach ($child in $allProcesses | Where-Object { [uint32]$_.ParentProcessId -eq $parentId }) {
    $childId = [uint32]$child.ProcessId
    if ($processIds.Add($childId)) {
      $pendingParentIds.Enqueue($childId)
    }
  }
}
foreach ($processId in $processIds) {
  Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}

$deadline = [DateTime]::UtcNow.AddSeconds(10)
do {
  $remaining = @(
    $processIds | ForEach-Object {
      Get-Process -Id ([int]$_) -ErrorAction SilentlyContinue
    }
  )
  if ($remaining.Count -eq 0) {
    exit 0
  }
  Start-Sleep -Milliseconds 200
} while ([DateTime]::UtcNow -lt $deadline)
throw "The Agent process did not stop before uninstall."
