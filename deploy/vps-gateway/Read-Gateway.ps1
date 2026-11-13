param(
    [Parameter(Mandatory=$true)][string]$TokenFile,
    [ValidateSet('health','status','emergency-stop')][string]$Action = 'status',
    [ValidateRange(1024,65535)][int]$Port = 18765
)
$ErrorActionPreference = 'Stop'
$token = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
if ($token -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid gateway token file.' }
$headers = @{Authorization="Bearer $token"}
$method = 'GET'
if ($Action -eq 'emergency-stop') {
    $method = 'POST'
    $headers['X-Request-Id'] = [guid]::NewGuid().ToString()
    $headers['X-Request-Time'] = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
}
Invoke-RestMethod -Uri "http://127.0.0.1:$Port/$Action" -Method $method -Headers $headers -TimeoutSec 6 -MaximumRedirection 0 -NoProxy -SkipHttpErrorCheck -StatusCodeVariable gatewayCode
if ($gatewayCode -ne 200) { exit 1 }
