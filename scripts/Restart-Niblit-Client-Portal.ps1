# Reload Portal source and SMTP settings without touching Niblit Core, MT5 or Freqtrade.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$matches=Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'python.exe' -and
  $_.CommandLine -match 'modules.server_manager:create_app' -and
  $_.CommandLine -match '8768'
}
foreach($process in $matches){
  Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
& 'C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Start-Niblit-Client-Portal.ps1'
