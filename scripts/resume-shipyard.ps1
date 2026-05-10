# resume-shipyard.ps1 — resume the most-recently-set-up factory target with
# console output mirrored to logs/console/.
#
# PowerShell sibling of resume-shipyard.sh — same behavior, same log layout.
#
# Usage:
#   .\scripts\resume-shipyard.ps1
#   .\scripts\resume-shipyard.ps1 --no-story-reviews
#
# Any extra arguments forward to `python -m src.main` after `--resume`.
$ErrorActionPreference = 'Stop'

# Anchor to the shipyard root regardless of where the script is invoked from.
Set-Location (Join-Path $PSScriptRoot '..')

if (-not (Test-Path factory.yaml)) {
    Write-Error "factory.yaml not found in $(Get-Location). Run scripts/preflight.sh against a target first."
    exit 2
}

# Use Python + PyYAML rather than text parsing so quoted paths with
# backslashes parse correctly. PyYAML is a shipyard dependency
# (see src/config.py); failure here means the venv isn't set up.
$Target = python -c "import yaml; print(yaml.safe_load(open('factory.yaml'))['target']['dir'])"

if ([string]::IsNullOrWhiteSpace($Target)) {
    Write-Error "factory.yaml has no target.dir set."
    exit 2
}

$null = New-Item -Path 'logs/console' -ItemType Directory -Force
$Timestamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
$Log = "logs/console/resume-$Timestamp.log"

Write-Host "Resuming target: $Target"
Write-Host "Console log:    $Log"
Write-Host '------------------------------------------------------------'

# Force Python's stdout/stderr to UTF-8 regardless of host locale. Without
# this, when Tee-Object sits in the pipeline the Python interpreter sees a
# non-TTY stdout and falls back to the system locale (cp1252 on Windows
# English), which crashes on any non-ASCII output (box-drawing rules,
# em-dashes, smart quotes). PYTHONUTF8=1 enables UTF-8 mode for the
# whole interpreter; PYTHONIOENCODING=utf-8 is belt-and-suspenders.
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# Disable Python's stdout block-buffering. When stdout is piped through
# Tee-Object, Python switches from line-buffering (TTY default) to 4KB
# block-buffering — print() output sits in a buffer until flush, arriving
# in the captured log out of chronological order with stderr logger
# output. PYTHONUNBUFFERED=1 keeps both streams flushing per line.
$env:PYTHONUNBUFFERED = '1'

# `2>&1` merges Python's stderr (logging) into stdout so Tee-Object captures
# both streams. PowerShell 5.1 wraps native-exe stderr lines in
# NativeCommandError, but Tee-Object still writes them to the file and
# forwards them to the host — which is what we want for visibility.
python -m src.main --rebuild $Target --resume @args 2>&1 | Tee-Object -FilePath $Log
exit $LASTEXITCODE
