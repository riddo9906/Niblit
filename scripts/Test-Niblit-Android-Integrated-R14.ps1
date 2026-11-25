# Read-only acceptance check for integrated Niblit R14 Android runtime.
# Does not authenticate, create sessions, or submit broker orders.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$release='D:\NiblitAIOS\releases\candidates\build-20261121-r14-mobile-integrated\niblit\niblit.exe'
$apk='D:\NiblitAIOS\releases\mobile\niblit-ai-v0.3.0-debug.apk'
if(-not (Test-Path $release)){throw 'Frozen R14 mobile executable missing'}
if(-not (Test-Path $apk)){throw 'Android v0.3.0 APK missing'}
$p=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'niblit.exe' -and $_.ExecutablePath -eq $release})
if($p.Count -ne 1){throw "Expected exactly one R14 mobile main executable, found $($p.Count)"}
$expected=@(
 @{Port=5202;Route='/health'},
 @{Port=8214;Route='/mobile/health'},
 @{Port=8768;Route='/api/health'}
)
foreach($service in $expected){
 $port=$service.Port
 $listener=@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop)
 if($listener.Count -ne 1 -or $listener[0].LocalAddress -ne '127.0.0.1' -or
    $listener[0].OwningProcess -ne $p[0].ProcessId){
    throw "Port $port is not owned by the same Niblit main executable on loopback"
 }
 $w=Invoke-WebRequest ("http://127.0.0.1:"+$port+$service.Route) -UseBasicParsing -TimeoutSec 8
 if($w.StatusCode -ne 200){throw "Service $port did not return HTTP 200"}
 Write-Output "R14_INTEGRATED_$port=HTTP_200_MAIN_EXE_PROCESS"
}
try{
 $w=Invoke-WebRequest 'http://127.0.0.1:8214/mobile/trading/sessions' -UseBasicParsing -TimeoutSec 6
 throw 'Unauthenticated trading session endpoint unexpectedly succeeded'
}catch{
 if(-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 401){
  throw 'Mobile trading endpoint did not reject missing Client Portal session'
 }
 Write-Output 'MOBILE_TRADING_UNAUTHENTICATED=HTTP_401'
}
$hash=(Get-FileHash $apk -Algorithm SHA256).Hash.ToLower()
Write-Output "APK_SHA256=$hash"
Write-Output "APK_BYTES=$((Get-Item $apk).Length)"
Write-Output "EXE_SHA256=$((Get-FileHash $release -Algorithm SHA256).Hash.ToLower())"
Write-Output 'BROKER_ORDERS_SUBMITTED_BY_VERIFICATION=0'
