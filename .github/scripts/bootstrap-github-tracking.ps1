param(
    [string]$Repo = "Ga420Low/project-os-core"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$labelsPath = Join-Path $root ".github/bootstrap/labels.json"
$issuesPath = Join-Path $root ".github/bootstrap/issues.json"

$labels = Get-Content $labelsPath -Raw | ConvertFrom-Json
foreach ($label in $labels) {
    gh label create $label.name --repo $Repo --color $label.color --description $label.description --force | Out-Null
}

$issues = Get-Content $issuesPath -Raw | ConvertFrom-Json
foreach ($issue in $issues) {
    $existing = gh issue list --repo $Repo --state all --limit 200 --search ('"' + $issue.title + '" in:title') --json title,number | ConvertFrom-Json
    $exact = $existing | Where-Object { $_.title -eq $issue.title }
    if ($exact) {
        continue
    }
    $bodyPath = Join-Path $root $issue.body_file
    $labelArgs = @()
    foreach ($label in $issue.labels) {
        $labelArgs += @("--label", $label)
    }
    gh issue create --repo $Repo --title $issue.title --body-file $bodyPath @labelArgs | Out-Null
}
