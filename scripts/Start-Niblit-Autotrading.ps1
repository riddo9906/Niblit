param([switch]$BackgroundCore)
$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$executable = Join-Path $bundleRoot 'niblit.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw 'Keep this launcher beside niblit.exe.' }
if (-not $env:NIBLIT_ENV_FILE) {
    $candidate = Split-Path -Parent $bundleRoot
    while ($candidate) {
        if ((Test-Path -LiteralPath (Join-Path $candidate 'niblit_core.py')) -and
            (Test-Path -LiteralPath (Join-Path $candidate 'niblit_io.py')) -and
            (Test-Path -LiteralPath (Join-Path $candidate '.env'))) {
            $env:NIBLIT_ENV_FILE = Join-Path $candidate '.env'
            break
        }
        $parent = Split-Path -Parent $candidate
        if ($parent -eq $candidate) { break }
        $candidate = $parent
    }
}
if (-not $env:NIBLIT_ENV_FILE -or -not (Test-Path -LiteralPath $env:NIBLIT_ENV_FILE)) {
    throw 'Select the existing private runtime profile with NIBLIT_ENV_FILE. No profile, credential or memory ledger was created.'
}
$probe = New-Object Net.Sockets.TcpClient
try {
    if ($probe.ConnectAsync('127.0.0.1',5000).Wait(500) -and $probe.Connected) {
        throw 'Core port 5000 is occupied. Close the previous Niblit desktop normally before switching releases.'
    }
} catch {
    if ($_.Exception.Message -like '*occupied*') { throw }
} finally { $probe.Dispose() }
# Source profile supplies the original memory authority and broker credentials.
# No persistent permission is edited and no trading/learning scope is activated.
$env:NIBLIT_TRADING_MODE = 'observe'
$env:NIBLIT_TRADING_ALLOW_EXECUTION = 'false'
$env:NIBLIT_FREQTRADE_ALLOW_EXECUTION = 'false'
$env:NIBLIT_FREQTRADE_ALLOW_CONTROL = 'false'
$env:NIBLIT_HEADLESS = '0'
$env:NIBLIT_API_PORT = '5000'
Write-Host 'Starting Core in observation mode. Open http://127.0.0.1:5000/market-desk/ for bounded demo-session review.'
Write-Host 'No session is activated by startup. Real-money submission is disabled.'
if ($BackgroundCore) {
    Write-Host 'Core will stay up independently of the Market Desk browser. Press Ctrl+C in this console to stop Core.'
    & $executable --serve
} else {
    & $executable
}
exit $LASTEXITCODE
