# Read-only Wednesday readiness; never grants sessions or places broker orders.
param(
    [string]$CoreUrl = 'http://127.0.0.1:5200',
    [string]$Repo = 'C:\Users\Riyaad\Documents\GitHub\Niblit'
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $Repo 'niblit-env\Scripts\python.exe'
$mt5 = Join-Path $Repo 'scripts\mt5_readonly_reconciliation.py'
$qdrant = Join-Path $Repo 'scripts\qdrant_readonly_check.py'
$memoryEnv = Join-Path $env:LOCALAPPDATA 'Niblit\memory-laboratory\.env'
$ticketLedger = 'D:\NiblitAIOS\data\trading-software-20261115\execution-control\runtime\trading-desk\mt5-orders.sqlite3'
if (-not (Test-Path $python)) { throw 'Niblit native Python environment missing' }
if (-not (Test-Path $mt5)) { throw 'Read-only MT5 audit missing' }
$blockers = [System.Collections.Generic.List[string]]::new()
$coreHealthy = $false
try {
    $health = Invoke-RestMethod ($CoreUrl.TrimEnd('/') + '/health') -TimeoutSec 6
    $coreHealthy = $health.status -eq 'ok' -and $health.core_bound -eq $true
} catch { $blockers.Add('Core health unavailable') }
if (-not $coreHealthy) { $blockers.Add('Core is not verified healthy') }
$positionMonitorHealthy = $false
try {
    $response = Invoke-WebRequest ($CoreUrl.TrimEnd('/') + '/api/trading/positions') -UseBasicParsing -TimeoutSec 5
    $positionMonitorHealthy = $response.StatusCode -eq 200
} catch {}
if (-not $positionMonitorHealthy) { $blockers.Add('Position-intelligence endpoint unavailable') }
$freqtradeApiReachable = $false
try {
    $socket = [System.Net.Sockets.TcpClient]::new()
    $freqtradeApiReachable = $socket.ConnectAsync('127.0.0.1',18081).Wait(400) -and $socket.Connected
    $socket.Dispose()
} catch { $freqtradeApiReachable = $false }
if (-not $freqtradeApiReachable) { $blockers.Add('Configured Freqtrade native API port 18081 unavailable') }
try {
    $broker = & $python $mt5 --ledger $ticketLedger --core-url $CoreUrl | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { $blockers.Add('Broker readback failed') }
} catch {
    $broker = $null
    $blockers.Add('Broker reconciliation check failed')
}
if ($broker) {
    if ($broker.state -ne 'observed') { $blockers.Add('MT5 account unavailable') }
    if (@($broker.unresolved_core_records).Count -gt 0) { $blockers.Add('Unresolved Core order records require investigation') }
    if (@($broker.positions | Where-Object { -not $_.core_ticket_number_match }).Count -gt 0) {
        $blockers.Add('One or more broker positions lack an exact Core ticket-number match')
    }
    if ($broker.account_mode -ne 'demo') { $blockers.Add('Account is not the validated demo profile') }
}
try {
    $memory = & $python -W ignore $qdrant --env-file $memoryEnv | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or -not $memory.ready) { $blockers.Add('Authenticated Qdrant read failed') }
} catch { $memory = $null; $blockers.Add('Qdrant check unavailable') }
$report = [ordered]@{
    checked_at = (Get-Date).ToString('o')
    scope = 'read-only; zero orders, activations or account changes'
    core_healthy = $coreHealthy
    position_monitor_healthy = $positionMonitorHealthy
    freqtrade_native_api_reachable = $freqtradeApiReachable
    account_mode = if ($broker) { $broker.account_mode } else { 'unavailable' }
    broker_position_count = if ($broker) { @($broker.positions).Count } else { $null }
    core_ticket_matches = if ($broker) { @($broker.positions | Where-Object core_ticket_number_match).Count } else { $null }
    qdrant_authenticated_read = [bool]($memory -and $memory.ready)
    blockers = @($blockers)
    live_execution_authorized = $false
    readiness = if ($blockers.Count) { 'blocked' } else { 'offline_preflight_only' }
}
$report | ConvertTo-Json -Depth 5
if ($blockers.Count) { exit 2 }
exit 0
