param([switch]$GrantMemoryAccess)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'niblit-env/Scripts/python.exe'
$profile = Join-Path $repoRoot '.env.memory-laboratory'
if (-not (Test-Path -LiteralPath $python)) { throw 'Install Core Python dependencies first.' }
& (Join-Path $PSScriptRoot 'Start-Memory-Laboratory.ps1')
$env:NIBLIT_MEMORY_LAB_ENABLED = '1'
$env:NIBLIT_MEMORY_LAB_ENV_FILE = $profile
$env:NIBLIT_MEMORY_LAB_NAMESPACE = 'desktop'
$env:NIBLIT_MEMORY_LAB_PRINCIPAL = 'desktop_operator'
$env:NIBLIT_MEMORY_LAB_LEDGER = Join-Path $env:LOCALAPPDATA 'Niblit/memory-laboratory/ledger.sqlite3'
Push-Location $repoRoot
try {
    if ($GrantMemoryAccess) {
        & $python -m modules.memory_laboratory.operator --env-file $profile --ledger $env:NIBLIT_MEMORY_LAB_LEDGER grant read ingest consolidate --confirm
        if ($LASTEXITCODE -ne 0) { throw 'Memory permission setup failed.' }
    }
    # Source Core includes Phase 6. The earlier frozen build does not.
    # Existing main.py retains responsibility for boot order and desktop UI.
    & $python main.py
} finally { Pop-Location }
