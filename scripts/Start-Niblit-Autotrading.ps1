param([switch]$BackgroundCore)
$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$executable = Join-Path $bundleRoot 'niblit.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw 'Keep this launcher beside niblit.exe.' }

# A packaged release owns its verified installation binding; don't silently
# replace the user's configured demo profile with an old observation-only one.
$anchorFile = Join-Path $bundleRoot 'release-runtime.json'
if (Test-Path -LiteralPath $anchorFile) {
    $anchor = Get-Content -LiteralPath $anchorFile -Raw | ConvertFrom-Json
    if (-not $anchor.configuration -or -not (Test-Path -LiteralPath $anchor.configuration)) {
        throw 'Packaged installation configuration is missing.'
    }
    $env:NIBLIT_ENV_FILE = $anchor.configuration
} elseif (-not $env:NIBLIT_ENV_FILE -or -not (Test-Path -LiteralPath $env:NIBLIT_ENV_FILE)) {
    throw 'Set NIBLIT_ENV_FILE to an existing private configuration for an unbound development build.'
}

$port = 5000
foreach ($line in (Get-Content -LiteralPath $env:NIBLIT_ENV_FILE)) {
    if ($line -match '^\s*NIBLIT_API_PORT\s*=\s*["'']?(\d+)') {
        $port = [int]$Matches[1]
        break
    }
}
if ($port -lt 1 -or $port -gt 65535) { throw 'Configured Core port is invalid.' }

$probe = New-Object Net.Sockets.TcpClient
try {
    if ($probe.ConnectAsync('127.0.0.1',$port).Wait(500) -and $probe.Connected) {
        throw "Core port $port is occupied. Close the existing Core normally before starting another release."
    }
} catch {
    if ($_.Exception.Message -like '*occupied*') { throw }
} finally { $probe.Dispose() }

# Do not override demo execution settings or approve any trading session here.
# Activation and ordinary session stop remain within Core's existing operator UI.
Write-Host "Starting configured Niblit Core on port $port."
Write-Host "Market Desk: http://127.0.0.1:$port/market-desk/"
if ($BackgroundCore) {
    & $executable --serve
} else {
    & $executable
}
exit $LASTEXITCODE
