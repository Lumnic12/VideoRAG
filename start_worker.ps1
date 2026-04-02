<#
.SYNOPSIS
    Start the Celery worker on Windows with --pool=solo.

.DESCRIPTION
    Uses the project's .venv Python to run a Celery worker that consumes
    the 'process_video' task queue.  --pool=solo is required on Windows
    because the default prefork pool uses multiprocessing.Process which
    is unreliable on Windows.

.EXAMPLE
    .\start_worker.ps1          # from project root
    .\start_worker.ps1 -Debug   # verbose debug logging
#>
param(
    [switch]$Debug
)

$loglevel = if ($Debug) { "debug" } else { "info" }

$backendDir = Join-Path $PSScriptRoot "backend"
$python     = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Backend .venv not found at $python. Run: cd backend && python -m venv .venv && pip install -r requirements.txt"
    exit 1
}

Write-Host "=== Semantic Video Synthesizer — Celery Worker ===" -ForegroundColor Cyan
Write-Host "  Backend : $backendDir"
Write-Host "  Python  : $python"
Write-Host "  Pool    : solo (Windows-compatible)"
Write-Host "  Log     : $loglevel`n"

Set-Location $backendDir

$env:PYTHONUTF8          = "1"
$env:FORKED_BY_MULTIPROCESSING = "1"

& $python -m celery `
    -A services.task_orchestrator worker `
    --loglevel=$loglevel `
    --pool=solo `
    --concurrency=1 `
    --without-gossip `
    --without-mingle `
    --without-heartbeat `
    --hostname="svs-worker@%h"
