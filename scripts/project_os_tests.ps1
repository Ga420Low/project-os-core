param(
    [ValidateSet("smoke", "gateway", "full", "all")]
    [string]$Suite = "smoke",
    [switch]$WithStrictDoctor,
    [switch]$WithOpenClawDoctor,
    [switch]$WithDocAudit
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $repoRoot "scripts\project_os_tests.py"
$command = @("py", $runner, "-Suite", $Suite)

if ($WithStrictDoctor.IsPresent) {
    $command += "-WithStrictDoctor"
}

if ($WithOpenClawDoctor.IsPresent) {
    $command += "-WithOpenClawDoctor"
}

if ($WithDocAudit.IsPresent) {
    $command += "-WithDocAudit"
}

Push-Location $repoRoot
try {
    & $command[0] $command[1..($command.Length - 1)]
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
