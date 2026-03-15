param(
    [int]$Port = 18789,
    [string]$TaskName = "OpenClaw Gateway"
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$openclawStateRoot = "D:\ProjectOS\runtime\openclaw"
$openclawConfigPath = Join-Path $openclawStateRoot "openclaw.json"
$startupPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\$TaskName.cmd"
$openclawBinary = (Get-Command "openclaw.cmd" -ErrorAction SilentlyContinue).Source
if (-not $openclawBinary) {
    $openclawBinary = (Get-Command "openclaw" -ErrorAction SilentlyContinue).Source
}
if (-not $openclawBinary) {
    throw "openclaw binary introuvable dans le PATH."
}

if (-not (Test-IsAdministrator)) {
    throw "Ce script doit etre lance dans une session PowerShell elevee (Administrateur)."
}

if (-not (Test-Path $openclawConfigPath)) {
    throw "openclaw.json introuvable: $openclawConfigPath"
}

$config = Read-JsonFile -Path $openclawConfigPath
$discordTokenRef = $config.channels.discord.accounts.'discord-main'.token
$gatewayTokenRef = $config.gateway.auth.token
if (-not ($discordTokenRef.source -eq "env" -and $discordTokenRef.id -eq "DISCORD_BOT_TOKEN")) {
    throw "Le runtime OpenClaw doit deja utiliser un SecretRef env pour le token Discord."
}
if (-not ($gatewayTokenRef.source -eq "env" -and $gatewayTokenRef.id -eq "OPENCLAW_GATEWAY_TOKEN")) {
    throw "Le runtime OpenClaw doit deja utiliser un SecretRef env pour le token gateway."
}
if (-not [Environment]::GetEnvironmentVariable("DISCORD_BOT_TOKEN", "User")) {
    throw "DISCORD_BOT_TOKEN n'est pas defini au niveau utilisateur Windows."
}
if (-not [Environment]::GetEnvironmentVariable("OPENCLAW_GATEWAY_TOKEN", "User")) {
    throw "OPENCLAW_GATEWAY_TOKEN n'est pas defini au niveau utilisateur Windows."
}

$env:OPENCLAW_STATE_DIR = $openclawStateRoot
$env:OPENCLAW_GATEWAY_PORT = "$Port"
$env:DISCORD_BOT_TOKEN = [Environment]::GetEnvironmentVariable("DISCORD_BOT_TOKEN", "User")
$env:OPENCLAW_GATEWAY_TOKEN = [Environment]::GetEnvironmentVariable("OPENCLAW_GATEWAY_TOKEN", "User")
$env:OPENCLAW_WINDOWS_TASK_NAME = $TaskName

Write-Host "[Project OS] stop existing OpenClaw gateway"
& $openclawBinary "gateway" "stop" | Out-Null

Write-Host "[Project OS] install managed OpenClaw gateway service"
& $openclawBinary "gateway" "install" "--force" "--runtime" "node" "--port" "$Port"
if ($LASTEXITCODE -ne 0) {
    throw "openclaw gateway install a echoue."
}

Write-Host "[Project OS] restart managed OpenClaw gateway service"
& $openclawBinary "gateway" "restart" | Out-Null
Start-Sleep -Seconds 6

$statusJson = & $openclawBinary "gateway" "status" "--json" "--token" $env:OPENCLAW_GATEWAY_TOKEN
if ($LASTEXITCODE -ne 0) {
    throw "Impossible de lire le status gateway apres installation."
}
$status = $statusJson | ConvertFrom-Json
$serviceLoaded = $status.service.loaded -eq $true
$runtimeStatus = [string]$status.service.runtime.status
$listenerBusy = [string]$status.port.status -eq "busy"
$rpcOk = $status.rpc.ok -eq $true

if (-not $serviceLoaded -or -not $listenerBusy -or -not $rpcOk) {
    throw "Le gateway installe n'est pas sain: loaded=$serviceLoaded runtime=$runtimeStatus port=$($status.port.status) rpc=$rpcOk"
}

if (Test-Path $startupPath) {
    Remove-Item -Path $startupPath -Force
    Write-Host "[Project OS] startup fallback removed: $startupPath"
}

Write-Host "[Project OS] managed OpenClaw gateway service installed successfully"
Write-Output ($status | ConvertTo-Json -Depth 20)
