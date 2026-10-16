param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("prepare", "verify")]
    [string]$Phase,
    [Parameter(Mandatory = $true)]
    [string]$Plan,
    [string]$PytestBasetemp,
    [switch]$ReviseRejected
)

$ErrorActionPreference = "Stop"
$planPath = (Resolve-Path -LiteralPath $Plan).Path

if ($Phase -eq "prepare") {
    python -m codegraph build
    if ($LASTEXITCODE -ne 0) { throw "CodeGraph build failed." }

    $simulateArgs = @("-m", "codegraph", "arch-simulate", "--plan", $planPath,
        "--save-prediction", "--proof", "--json")
    if ($ReviseRejected) { $simulateArgs += "--revise-rejected" }
    $simulation = python @simulateArgs
    if ($LASTEXITCODE -ne 0) { throw "Architecture simulation/proof failed." }
    $simulationText = $simulation -join "`n"
    $simulationText | Write-Output
    $simulationResult = $simulationText | ConvertFrom-Json
    $proofAccepted = $simulationResult.proof.status -eq "PROVEN_SAFE"
    $checksRan = $simulationResult.status -eq "simulated" -and $simulationResult.function_checks_available
    if ($simulationResult.verdict -eq "REJECT" -or -not $proofAccepted -or -not $checksRan) {
        throw "Plan did not pass both gates (verdict=$($simulationResult.verdict), proof=$($simulationResult.proof.status), checks=$($simulationResult.status)). Revise it before implementation."
    }

    if ($simulationResult.revision) {
        $revisedPath = Join-Path (Get-Location) ".codegraph/planning/revised_arch_plan.json"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $revisedPath) | Out-Null
        $simulationResult.revised_plan | ConvertTo-Json -Depth 50 |
            Set-Content -LiteralPath $revisedPath -Encoding utf8
        Write-Host "Revision feedback: removed $($simulationResult.revision.dropped_changes.Count) individually rejected change(s). Review the reasons and revised plan at $revisedPath before implementation."
    }

    Write-Host "Prediction saved. Implement the approved change, then run this script with -Phase verify."
    exit 0
}

if ($PytestBasetemp) {
    python -m pytest --basetemp $PytestBasetemp -q
} else {
    python -m pytest -q
}
if ($LASTEXITCODE -ne 0) { throw "Tests failed; rebuild and reconciliation were not run." }

python -m codegraph build
if ($LASTEXITCODE -ne 0) { throw "Post-change CodeGraph build failed." }

$report = python -m codegraph arch-reconcile --json
if ($LASTEXITCODE -ne 0) { throw "Architecture reconciliation failed to run." }
$report | Write-Output
$parsed = $report | ConvertFrom-Json
if (-not $parsed.matches) { throw "The rebuilt graph differs from the saved prediction." }

Write-Host "Dogfooding cycle verified: tests pass and predicted graph matches the rebuild."
