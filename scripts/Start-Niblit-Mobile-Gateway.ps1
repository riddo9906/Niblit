# Niblit mobile API + desktop preview; loopback-only, never public/LAN.
[CmdletBinding()]
param([int]$Port=8214)
$ErrorActionPreference='Stop'
if($Port -ne 8214){throw 'Mobile gateway port must match the verified loopback configuration'}
$root='C:\Users\Riyaad\Documents\GitHub\niblit-cloud-server'
$python=Join-Path $root 'venv\Scripts\python.exe'
$logs='D:\NiblitAIOS\diagnostics\android-frontend-20261121'
if(!(Test-Path $python)){throw 'Cloud Python environment missing'}
$occupied=Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if($occupied){
  try{$response=Invoke-WebRequest "http://127.0.0.1:$Port/mobile/" -UseBasicParsing -TimeoutSec 4
      if($response.StatusCode -eq 200){Write-Output 'Niblit mobile gateway already running; no duplicate started';return}}catch{}
  throw 'Mobile gateway port occupied by an unknown service'
}
New-Item -ItemType Directory -Force -Path $logs|Out-Null
$proc=Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.mobile_gateway:app',
  '--host','127.0.0.1','--port',"$Port",'--no-proxy-headers') -WorkingDirectory $root -PassThru
Write-Output "Niblit mobile gateway started PID $($proc.Id), local preview http://127.0.0.1:$Port/mobile/"
