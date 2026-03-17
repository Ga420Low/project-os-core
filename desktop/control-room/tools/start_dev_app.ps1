$ErrorActionPreference = "Stop"

try {
  $root = Split-Path -Parent $PSScriptRoot
  Set-Location $root

  if (-not (Test-Path (Join-Path $root "node_modules"))) {
    & npm.cmd install
    if ($LASTEXITCODE -ne 0) {
      throw "npm install failed with exit code $LASTEXITCODE"
    }
  }

  & npm.cmd run dev
  if ($LASTEXITCODE -ne 0) {
    throw "npm run dev failed with exit code $LASTEXITCODE"
  }
} catch {
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show(
    $_.Exception.Message,
    "Project OS Dev",
    [System.Windows.MessageBoxButton]::OK,
    [System.Windows.MessageBoxImage]::Error
  ) | Out-Null
  exit 1
}
