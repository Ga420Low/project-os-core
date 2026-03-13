$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcPath = Join-Path $repoRoot "src"

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $srcPath
}

Write-Host "[Project OS] bootstrap"
py -m project_os_core bootstrap --strict

Write-Host "[Project OS] doctor"
py -m project_os_core doctor --strict

Write-Host "[Project OS] health snapshot"
py -m project_os_core health snapshot
