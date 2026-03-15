param(
    [ValidateSet("smoke", "gateway", "full", "all")]
    [string]$Suite = "smoke",
    [switch]$WithStrictDoctor,
    [switch]$WithOpenClawDoctor,
    [switch]$WithDocAudit
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$entry = Join-Path $repoRoot "scripts\project_os_entry.py"
$configPath = Join-Path $repoRoot "config\storage_roots.local.json"
$policyPath = Join-Path $repoRoot "config\runtime_policy.local.json"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "[Project OS][tests] $Label"
    & $Command[0] $Command[1..($Command.Length - 1)]
    $exitCode = $LASTEXITCODE
    $stopwatch.Stop()
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode after $($stopwatch.Elapsed.ToString())."
    }
    Write-Host "[Project OS][tests] $Label OK in $($stopwatch.Elapsed.ToString())"
}

Push-Location $repoRoot
try {
    switch ($Suite) {
        "smoke" {
            Invoke-CheckedCommand -Label "pytest smoke (critical core surfaces)" -Command @(
                "py", "-m", "pytest",
                "tests/unit/test_router.py",
                "tests/unit/test_mission_chain.py",
                "tests/unit/test_api_run_service.py",
                "tests/unit/test_api_run_dashboard.py",
                "-q",
                "--maxfail=1"
            )
        }
        "gateway" {
            Invoke-CheckedCommand -Label "pytest gateway surfaces" -Command @(
                "py", "-m", "pytest",
                "tests/unit/test_router.py",
                "tests/unit/test_openclaw_live.py",
                "tests/unit/test_openclaw_gateway_adapter.py",
                "tests/unit/test_api_run_service.py",
                "-q"
            )
        }
        "full" {
            Invoke-CheckedCommand -Label "pytest full (unit + integration)" -Command @(
                "py", "-m", "pytest", "tests/unit", "tests/integration", "-q"
            )
        }
        "all" {
            Invoke-CheckedCommand -Label "pytest smoke (critical core surfaces)" -Command @(
                "py", "-m", "pytest",
                "tests/unit/test_router.py",
                "tests/unit/test_mission_chain.py",
                "tests/unit/test_api_run_service.py",
                "tests/unit/test_api_run_dashboard.py",
                "-q",
                "--maxfail=1"
            )
            Invoke-CheckedCommand -Label "pytest gateway surfaces" -Command @(
                "py", "-m", "pytest",
                "tests/unit/test_router.py",
                "tests/unit/test_openclaw_live.py",
                "tests/unit/test_openclaw_gateway_adapter.py",
                "tests/unit/test_api_run_service.py",
                "-q"
            )
            Invoke-CheckedCommand -Label "pytest full (unit + integration)" -Command @(
                "py", "-m", "pytest", "tests/unit", "tests/integration", "-q"
            )
        }
    }

    if ($WithStrictDoctor.IsPresent) {
        Invoke-CheckedCommand -Label "doctor --strict" -Command @(
            "py", $entry, "--config-path", $configPath, "--policy-path", $policyPath, "doctor", "--strict"
        )
    }

    if ($WithOpenClawDoctor.IsPresent) {
        Invoke-CheckedCommand -Label "openclaw doctor" -Command @(
            "py", $entry, "--config-path", $configPath, "--policy-path", $policyPath, "openclaw", "doctor"
        )
    }

    if ($WithDocAudit.IsPresent) {
        Invoke-CheckedCommand -Label "docs audit" -Command @(
            "py", $entry, "docs", "audit"
        )
    }
}
finally {
    Pop-Location
}
