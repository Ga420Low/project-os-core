param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8765,
    [int]$Limit = 8,
    [int]$RefreshSeconds = 4,
    [switch]$OpenBrowser
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$entry = Join-Path $repoRoot "scripts\project_os_entry.py"

$args = @(
    $entry,
    "api-runs",
    "dashboard",
    "--host", $Host,
    "--port", "$Port",
    "--limit", "$Limit",
    "--refresh-seconds", "$RefreshSeconds"
)

if ($OpenBrowser.IsPresent) {
    $args += "--open-browser"
}

py @args
