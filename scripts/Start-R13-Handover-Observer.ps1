# Starts ONLY the read-only MT5 handover observer for isolated r13.
# It never runs trading activation or sends broker orders.
param([switch]$Once)
$ErrorActionPreference='Stop'
$root='C:\Users\Riyaad\Documents\GitHub\Niblit'
$python=Join-Path $root 'niblit-env\Scripts\python.exe'
$script=Join-Path $root 'scripts\mt5_handover_observer.py'
$out='D:\NiblitAIOS\data\r13-observe-20261121\mt5-handover-latest.json'
if(-not (Test-Path $python) -or -not (Test-Path $script)){
 throw 'Native Python environment or observer script is missing'
}
try{$r=Invoke-WebRequest 'http://127.0.0.1:5200/health' -UseBasicParsing -TimeoutSec 5}catch{throw 'R12 Core health unavailable'}
if($r.StatusCode -ne 200){throw 'R12 Core health not accepted'}
if(-not $Once){
 $existing=Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'python.exe' -and $_.CommandLine -like '*mt5_handover_observer.py*'}
 if($existing){throw 'Read-only observer already running; do not start a duplicate'}
}
Set-Location $root
if($Once){ & $python $script --output $out }
else{ & $python -u $script --watch --interval 30 --output $out }
exit $LASTEXITCODE
