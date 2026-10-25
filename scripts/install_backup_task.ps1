$ErrorActionPreference = "Stop"

$Script = Join-Path $PSScriptRoot "run_backup.ps1"
$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "SteelMarketDailyBackup"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At 2:30AM
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Steel market encrypted daily backup" `
        -Force | Out-Null
    Write-Output "Scheduled task '$TaskName' installed (daily 02:30, current user)."
    Write-Output "It only runs while you are logged on; missed runs start when available."
} catch {
    Write-Error "Failed to register scheduled task. Run PowerShell as administrator and retry. $($_.Exception.Message)"
    exit 1
}
