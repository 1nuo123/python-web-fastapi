param(
  [Parameter(Mandatory = $true)][string]$ExecutablePath
)
$action = New-ScheduledTaskAction -Execute $ExecutablePath -WorkingDirectory (Split-Path $ExecutablePath)
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "CodexRemoteAgent" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
