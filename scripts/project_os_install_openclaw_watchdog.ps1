param(
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$watchdogScript = Join-Path $repoRoot "scripts\project_os_openclaw_watchdog.ps1"
$policyPath = Join-Path $repoRoot "config\runtime_policy.local.json"

if (-not (Test-Path $watchdogScript)) {
    throw "Script watchdog introuvable: $watchdogScript"
}
if (-not (Test-Path $policyPath)) {
    throw "Policy runtime introuvable: $policyPath"
}

$policy = Read-JsonFile -Path $policyPath
$openclawConfig = $policy.openclaw_config
$taskName = if ($openclawConfig.windows_watchdog_task_name) { [string]$openclawConfig.windows_watchdog_task_name } else { "Project OS OpenClaw Watchdog" }
$intervalMinutes = if ($openclawConfig.self_heal_check_interval_minutes) { [int]$openclawConfig.self_heal_check_interval_minutes } else { 2 }
$startupPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\$taskName.cmd"
if ($intervalMinutes -lt 1) {
    throw "self_heal_check_interval_minutes doit etre >= 1."
}

$powershellExe = (Get-Command "powershell.exe" -ErrorAction SilentlyContinue).Source
if (-not $powershellExe) {
    $powershellExe = (Get-Command "powershell" -ErrorAction SilentlyContinue).Source
}
if (-not $powershellExe) {
    throw "powershell.exe introuvable."
}

$argument = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdogScript`""
$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $argument
$intervalTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $intervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$installMode = "register-scheduled-task"
$logonMode = "scheduled-task"
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($intervalTrigger, $logonTrigger) -Principal $principal -Settings $settings -Force | Out-Null
    if (Test-Path $startupPath) {
        Remove-Item -Path $startupPath -Force
    }
}
catch {
    $installMode = "schtasks-minute"
    $schtasksTrigger = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""$watchdogScript"""
    schtasks /Create /SC MINUTE /MO $intervalMinutes /TN $taskName /TR $schtasksTrigger /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Impossible de creer la tache watchdog via schtasks."
    }
    $startupContent = "@echo off`r`npowershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""$watchdogScript""`r`n"
    Set-Content -Path $startupPath -Value $startupContent -Encoding Ascii
    $logonMode = "startup-folder"
}

$runNowExitCode = $null
if ($RunNow.IsPresent) {
    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $watchdogScript
    $runNowExitCode = $LASTEXITCODE
}

$task = Get-ScheduledTask -TaskName $taskName
[pscustomobject]@{
    task_name = $taskName
    interval_minutes = $intervalMinutes
    watchdog_script = $watchdogScript
    user = "$env:USERDOMAIN\$env:USERNAME"
    state = $task.State.ToString()
    install_mode = $installMode
    logon_mode = $logonMode
    startup_path = $startupPath
    run_now = [bool]$RunNow.IsPresent
    run_now_exit_code = $runNowExitCode
} | ConvertTo-Json -Depth 5
