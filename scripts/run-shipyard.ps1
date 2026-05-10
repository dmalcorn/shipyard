# run-shipyard.ps1 — fresh factory run against a specified target with
# console output mirrored to logs/console/.
#
# PowerShell sibling of run-shipyard.sh — same behavior, same log layout.
# For resuming an in-flight target, use resume-shipyard.ps1 instead.
#
# Usage:
#   .\scripts\run-shipyard.ps1 "C:\path\to\target"
#   .\scripts\run-shipyard.ps1 "C:\path\to\target" --no-story-reviews
$ErrorActionPreference = 'Stop'

if ($args.Count -lt 1) {
    Write-Error "Usage: .\scripts\run-shipyard.ps1 <target-dir> [extra args...]"
    Write-Host "       For an in-flight resume, use scripts/resume-shipyard.ps1" -ForegroundColor Yellow
    exit 2
}

$Target = $args[0]
$Extra = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }

Set-Location (Join-Path $PSScriptRoot '..')

$null = New-Item -Path 'logs/console' -ItemType Directory -Force
$Timestamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
$Log = "logs/console/run-$Timestamp.log"

Write-Host "Target:      $Target"
Write-Host "Console log: $Log"
Write-Host '------------------------------------------------------------'

# Force UTF-8 stdout — see resume-shipyard.ps1 for full rationale.
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'  # see resume-shipyard.ps1 for rationale

python -m src.main --rebuild $Target @Extra 2>&1 | Tee-Object -FilePath $Log
exit $LASTEXITCODE
