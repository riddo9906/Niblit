param([switch]$GrantMemoryAccess)
$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$executable = Join-Path $bundleRoot 'niblit.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw 'Place this launcher beside the packaged niblit.exe.'
}

# The frontend in this build connects to Core on port 5000.
$portProbe = New-Object System.Net.Sockets.TcpClient
try {
    $pending = $portProbe.ConnectAsync('127.0.0.1', 5000)
    if ($pending.Wait(700) -and $portProbe.Connected) {
        Write-Host 'Another app is using Niblit port 5000. Close the previous Niblit app before starting this testing build.'
        Read-Host 'Press Enter to close'
        exit 1
    }
} catch {
    # A refused connection means the Core port is available.
} finally {
    $portProbe.Dispose()
}

$testingData = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Niblit\testing-20261025'
try {
    $existingTrading = Invoke-RestMethod 'http://127.0.0.1:8100/health' -TimeoutSec 2
} catch { $existingTrading = $null }
if ($existingTrading -and ($existingTrading.backend -ne 'paper' -or $existingTrading.market_data.provider -ne 'replay')) {
    Write-Host 'An older trading runtime is still using port 8100. Close the previous Niblit runtime before launching this paper build.'
    Read-Host 'Press Enter to close'
    exit 1
}
New-Item -ItemType Directory -Path $testingData -Force | Out-Null
$env:NIBLIT_MEMORY_PATH = Join-Path $testingData 'memory.json'
$env:NIBLIT_LLM_CHAT_DB_PATH = Join-Path $testingData 'chat.sqlite'
$env:FUSED_MEMORY_DB_PATH = Join-Path $testingData 'fused.sqlite'
$env:NIBLIT_RUNTIME_LOG_FILE = Join-Path $testingData 'runtime.jsonl'
$env:NIBLIT_UNIFIED_RUNTIME_STATE = Join-Path $testingData 'unified-runtime.json'
$env:NIBLIT_PERMISSION_FILE = Join-Path $testingData 'permissions.json'
$memoryProfile = Join-Path $env:LOCALAPPDATA 'Niblit/memory-laboratory/.env'
if (Test-Path -LiteralPath $memoryProfile) {
    $env:NIBLIT_MEMORY_LAB_ENABLED = '1'
    $env:NIBLIT_MEMORY_LAB_ENV_FILE = $memoryProfile
    $env:NIBLIT_MEMORY_LAB_NAMESPACE = 'desktop'
    $env:NIBLIT_MEMORY_LAB_PRINCIPAL = 'desktop_operator'
    $env:NIBLIT_MEMORY_LAB_LEDGER = Join-Path $env:LOCALAPPDATA 'Niblit/memory-laboratory/ledger.sqlite3'
    if ($GrantMemoryAccess) {
        & $executable --memory-lab-operator --env-file $memoryProfile --ledger $env:NIBLIT_MEMORY_LAB_LEDGER grant read ingest consolidate --confirm
        if ($LASTEXITCODE -ne 0) { throw 'Memory permission setup failed.' }
    }
}
$sourceCandidate = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $bundleRoot))
if (-not $env:NIBLIT_ENV_FILE -and (Test-Path -LiteralPath (Join-Path $sourceCandidate 'niblit_core.py')) -and
    (Test-Path -LiteralPath (Join-Path $sourceCandidate '.env'))) {
    $env:NIBLIT_ENV_FILE = Join-Path $sourceCandidate '.env'
}
if (-not $env:NIBLIT_WORKSPACE_ROOT) {
    if (Test-Path -LiteralPath (Join-Path $sourceCandidate 'niblit_core.py')) {
        $env:NIBLIT_WORKSPACE_ROOT = $sourceCandidate
    } else {
        $env:NIBLIT_WORKSPACE_ROOT = Join-Path $testingData 'workspace'
        New-Item -ItemType Directory -Path $env:NIBLIT_WORKSPACE_ROOT -Force | Out-Null
    }
}
$env:NIBLIT_HEADLESS = '0'
$env:NIBLIT_LOW_RESOURCE_MODE = '0'
$env:NIBLIT_SKIP_INIT_WAIT = '0'
$env:NIBLIT_TRADING_BACKEND = 'paper'
$env:NIBLIT_TRADING_MODE = 'observe'
$env:NIBLIT_TRADING_ALLOW_EXECUTION = 'false'
$env:NIBLIT_FREQTRADE_ALLOW_EXECUTION = 'false'
$paperData = Join-Path $testingData 'paper'
New-Item -ItemType Directory -Path $paperData -Force | Out-Null
$env:NIBLIT_PAPER_STATE_FILE = Join-Path $paperData 'account.json'
$env:NIBLIT_TRADING_CONTROL_FILE = Join-Path $paperData 'control.json'
$env:NIBLIT_REPLAY_STATE_FILE = Join-Path $paperData 'replay.json'
$env:NIBLIT_EXECUTION_DB = Join-Path $paperData 'executions.sqlite'
$env:NIBLIT_REPLAY_DATA_DIR = Join-Path $bundleRoot 'freqtrade\data'
$env:NIBLIT_MARKET_DATA_PROVIDER = 'replay'
$env:NIBLIT_MARKET_DATA_TIMEFRAME = '1h'
$env:NIBLIT_STRATEGY_API_PORT = '8150'
$env:NIBLIT_LLM_PROVIDER = 'qwen'
$env:NIBLIT_API_PORT = '5000'
$env:NIBLIT_TRADING_API_PORT = '8100'
$env:NIBLIT_CLOUD_SERVER_PRIMARY_PORT = '8000'
$env:NIBLIT_PORT = '8000'
$env:NIBLIT_CLOUD_SERVER_URL = 'http://127.0.0.1:8000'
$env:NIBLIT_CLOUD_BASE_URL = 'http://127.0.0.1:8000'
Write-Host "Niblit testing memory: $testingData"
Write-Host 'Starting the desktop with local inference and paper/observe trading.'
Set-Location -LiteralPath $testingData
& $executable
if ($LASTEXITCODE -ne 0) {
    Read-Host 'Niblit stopped with an error. Review the output, then press Enter'
}
