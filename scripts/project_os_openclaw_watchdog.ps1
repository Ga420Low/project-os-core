param(
    [switch]$IgnoreCooldown
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$entry = Join-Path $repoRoot "scripts\project_os_entry.py"
$configPath = Join-Path $repoRoot "config\storage_roots.local.json"
$policyPath = Join-Path $repoRoot "config\runtime_policy.local.json"

$python = (Get-Command "py" -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $python = (Get-Command "python" -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    throw "Impossible de trouver py/python pour lancer le watchdog OpenClaw."
}

$command = @(
    $python,
    $entry,
    "--config-path", $configPath,
    "--policy-path", $policyPath,
    "openclaw",
    "self-heal"
)
if ($IgnoreCooldown.IsPresent) {
    $command += "--ignore-cooldown"
}

& $command[0] $command[1..($command.Length - 1)]
exit $LASTEXITCODE
