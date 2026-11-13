param([Parameter(Mandatory=$true)][string]$ConfigPath, [switch]$EnableTradingControls)
$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$configFile = (Resolve-Path -LiteralPath $ConfigPath).Path
$config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
if (-not ($config.dry_run -is [bool])) { throw 'The private profile must explicitly set dry_run to true or false.' }
if ($config.dry_run -eq $false -and $EnableTradingControls.IsPresent) { throw 'Real-money engine controls are disabled in this release. Live profiles support stopped observation only.' }
if ($config.initial_state -ne 'stopped') { throw 'This launcher requires initial_state=stopped. Start trading deliberately through Freqtrade after reviewing the profile.' }
if ($config.api_server.listen_ip_address -ne '127.0.0.1' -or $config.api_server.listen_port -ne 18080) { throw 'Set the Freqtrade API to 127.0.0.1:18080.' }
if (-not $config.api_server.username -or -not $config.api_server.password) { throw 'Private Freqtrade API credentials are required.' }
if ($config.dry_run -eq $false -and (-not $config.exchange.key -or -not $config.exchange.secret)) { throw 'Configure exchange credentials in your private live profile first.' }
foreach ($port in @(5000,8000,8100,18080)) {
    $probe = New-Object System.Net.Sockets.TcpClient
    $connected = $false
    try {
        $connected = $probe.ConnectAsync('127.0.0.1',$port).Wait(300) -and $probe.Connected
    } catch {
        $connected = $false
    } finally { $probe.Dispose() }
    if ($connected) { throw "Port $port is already in use; close the other Niblit profile first." }
}
# Avoid inherited Freqtrade overrides silently changing the selected profile.
Get-ChildItem Env: | Where-Object Name -Like 'FREQTRADE__*' | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
$env:NIBLIT_TRADING_BACKEND = 'freqtrade'
$env:NIBLIT_TRADING_MODE = 'observe'
$env:NIBLIT_FREQTRADE_ALLOW_EXECUTION = 'false'
$env:NIBLIT_FREQTRADE_ALLOW_CONTROL = ([string]$EnableTradingControls.IsPresent).ToLowerInvariant()
$env:NIBLIT_TRADING_ALLOW_EXECUTION = 'false'
$env:NIBLIT_FREQTRADE_DRY_RUN = ([string]$config.dry_run).ToLowerInvariant()
$env:NIBLIT_FREQTRADE_BASE_URL = 'http://127.0.0.1:18080'
$env:NIBLIT_FREQTRADE_USERNAME = $config.api_server.username
$env:NIBLIT_FREQTRADE_PASSWORD = $config.api_server.password
$env:NIBLIT_MARKET_DATA_PROVIDER = 'ccxt'
$env:NIBLIT_MARKET_DATA_EXCHANGE = $config.exchange.name
$env:NIBLIT_MARKET_DATA_MARKET_TYPE = 'spot'
$env:NIBLIT_MARKET_DATA_TIMEFRAME = '1h'
$env:NIBLIT_TRADING_API_PORT = '8100'
$env:NIBLIT_API_PORT = '5000'
$env:NIBLIT_CLOUD_SERVER_PRIMARY_PORT = '8000'
$env:NIBLIT_PORT = '8000'
$env:NIBLIT_CLOUD_SERVER_URL = 'http://127.0.0.1:8000'
$env:NIBLIT_CLOUD_BASE_URL = 'http://127.0.0.1:8000'
$env:NIBLIT_HEADLESS = '0'
$env:NIBLIT_LOW_RESOURCE_MODE = '0'
$state = Join-Path (Split-Path -Parent $configFile) 'niblit-state'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$env:NIBLIT_PERMISSION_FILE = Join-Path $state 'operator-permissions.json'
# Profile-local authorization for explicit human engine controls only.
$controlPermission = @{}
if (Test-Path -LiteralPath $env:NIBLIT_PERMISSION_FILE) {
    $previousPermissions = Get-Content -LiteralPath $env:NIBLIT_PERMISSION_FILE -Raw | ConvertFrom-Json
    foreach ($property in $previousPermissions.PSObject.Properties) { $controlPermission[$property.Name] = $property.Value }
}
$controlPermission['command.operator.freqtrade'] = [bool]$EnableTradingControls.IsPresent
[IO.File]::WriteAllText($env:NIBLIT_PERMISSION_FILE, ($controlPermission | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
$env:NIBLIT_EXECUTION_DB = Join-Path $state 'executions.sqlite'
$engine = Join-Path $bundleRoot 'freqtrade/niblit-freqtrade-worker.exe'
$runtime = Join-Path $bundleRoot 'lean-algos/niblit-lean-algos.exe'
$owned = @()
try {
    $owned += Start-Process -FilePath $engine -ArgumentList @('--engine','trade','--config',('"' + $configFile + '"')) -WindowStyle Hidden -PassThru -WorkingDirectory $state -RedirectStandardOutput (Join-Path $state 'freqtrade.stdout.log') -RedirectStandardError (Join-Path $state 'freqtrade.stderr.log')
    $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($config.api_server.username + ':' + $config.api_server.password))
    $ready = $false
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline -and -not $owned[0].HasExited) {
        try {
            $remote = Invoke-RestMethod 'http://127.0.0.1:18080/api/v1/show_config' -Headers @{Authorization=('Basic ' + $basic)} -TimeoutSec 2
            if ($remote.dry_run -ne $config.dry_run -or $remote.state -ne 'stopped') { throw 'Engine identity does not match the stopped profile.' }
            $ready = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Freqtrade did not become ready. Review freqtrade.stderr.log in the profile state folder.' }
    $owned += Start-Process -FilePath $runtime -WindowStyle Hidden -PassThru -WorkingDirectory $state -RedirectStandardOutput (Join-Path $state 'adapter.stdout.log') -RedirectStandardError (Join-Path $state 'adapter.stderr.log')
    $ready = $false
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline -and -not $owned[1].HasExited) {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8100/health' -TimeoutSec 2
            if ($health.backend -eq 'freqtrade' -and $health.healthy -and $health.mode -eq 'observe') { $ready = $true; break }
        } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Niblit Freqtrade adapter did not become ready; review adapter.stderr.log.' }
    Write-Host 'Freqtrade engine selected. Trading starts STOPPED; Niblit force-entry/exit remains disabled.'
    Write-Host ('Human start/stop controls enabled: ' + $EnableTradingControls.IsPresent)
    & (Join-Path $bundleRoot 'niblit.exe')
} finally {
    foreach ($process in $owned) { if (-not $process.HasExited) { Stop-Process -Id $process.Id } }
}
