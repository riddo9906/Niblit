param(
 [string]$Terminal='C:\Program Files\MetaTrader 5\terminal64.exe',
 [string]$SafeConfig='C:\NiblitGateway\config\mt5-observe.ini',
 [string]$Log='C:\NiblitGateway\logs\terminal-startup.jsonl'
)
$ErrorActionPreference='Stop'
function Record-Startup($Event,$Details){
 $row=@{at=[DateTime]::UtcNow.ToString('o');event=$Event;session=(Get-Process -Id $PID).SessionId;details=$Details}
 $row | ConvertTo-Json -Compress | Add-Content -LiteralPath $Log -Encoding utf8
}
try {
 if(Test-Path -LiteralPath $Log){
  if((Get-Item -LiteralPath $Log).Length -gt 1000000){Move-Item -LiteralPath $Log -Destination ($Log+'.1') -Force}
 }
 Record-Startup 'starting' @{terminal=$Terminal}
 $session=(Get-Process -Id $PID).SessionId
 if($session -eq 0){throw 'Interactive Windows sign-in required'}
 $existing=@(Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" | Where-Object {$_.SessionId -eq $session})
 if($existing.Count){
  if($existing.Count -ne 1 -or $existing[0].ExecutablePath -ne $Terminal){throw 'Ambiguous MT5 session; manual inspection required'}
  Record-Startup 'existing_terminal' @{pid=$existing[0].ProcessId}
  exit 0
 }
 if(!(Test-Path -LiteralPath $Terminal) -or !(Test-Path -LiteralPath $SafeConfig)){throw 'Explicit MT5 executable or safe configuration missing'}
 $started=Start-Process -FilePath $Terminal -ArgumentList ("/config:{0}" -f $SafeConfig) -WorkingDirectory (Split-Path $Terminal) -WindowStyle Minimized -PassThru
 # Exactly one launch. Observe startup for at most 30 seconds; never loop-launch.
 for($n=0;$n -lt 15;$n++){
  Start-Sleep -Seconds 2
  $found=@(Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" | Where-Object {$_.SessionId -eq $session})
  if($found.Count -gt 1){throw 'Duplicate MT5 detected; manual inspection required'}
  if($found.Count -eq 1 -and $found[0].ExecutablePath -eq $Terminal){
   Record-Startup 'process_started_not_broker_proof' @{pid=$found[0].ProcessId}
   exit 0
  }
 }
 throw 'MT5 did not remain running within startup deadline'
} catch {
 try {Record-Startup 'failed' @{error_type=$_.Exception.GetType().Name;reason=$_.Exception.Message}} catch {}
 exit 1
}
