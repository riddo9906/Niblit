$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$port = 5000
$anchorFile = Join-Path $bundleRoot 'release-runtime.json'
$configFile = $env:NIBLIT_ENV_FILE
if (Test-Path -LiteralPath $anchorFile) {
    $anchor = Get-Content -LiteralPath $anchorFile -Raw | ConvertFrom-Json
    $configFile = $anchor.configuration
}
if ($configFile -and (Test-Path -LiteralPath $configFile)) {
    foreach ($line in (Get-Content -LiteralPath $configFile)) {
        if ($line -match '^\s*NIBLIT_API_PORT\s*=\s*["'']?(\d+)') {
            $port = [int]$Matches[1]
            break
        }
    }
}
if ($port -lt 1 -or $port -gt 65535) { throw 'Invalid Niblit Core port.' }
$url = "http://127.0.0.1:$port/market-desk/"
Start-Process $url
