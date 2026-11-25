# Four-model Niblit Cloud preview (includes Qwen14B via sidecar), without changing production Cloud.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root='C:\Users\Riyaad\Documents\GitHub\niblit-cloud-server'
$python=Join-Path $root 'venv\Scripts\python.exe'
$logs='D:\NiblitAIOS\diagnostics\android-frontend-20261121'
if(!(Test-Path $python)){throw 'Cloud Python environment missing'}
$occupied=Get-NetTCPConnection -LocalPort 8212 -State Listen -ErrorAction SilentlyContinue
if($occupied){
  try{$response=Invoke-RestMethod 'http://127.0.0.1:8212/health' -TimeoutSec 5
    if($response.status -eq 'ready' -and $response.models -contains 'qwen2.5-coder-14b'){
      Write-Output 'Four-model Cloud preview already healthy; no duplicate started';return}}catch{}
  throw 'Port 8212 is occupied by an unexpected service'
}
$env:NIBLIT_PORT='8212'
$env:NIBLIT_CLOUD_BIND_HOST='127.0.0.1'
$env:NIBLIT_HOST='127.0.0.1'
$env:NIBLIT_CLOUD_BASE_URL='http://127.0.0.1:8212'
$env:NIBLIT_GGUF_MODEL_DIR='D:\Models'
$env:NIBLIT_MODEL_PATH='D:\Models\qwen2.5-coder-3b-instruct-q4_k_m.gguf'
$env:NIBLIT_DEFAULT_MODEL_PATH=$env:NIBLIT_MODEL_PATH
$env:NIBLIT_DEFAULT_MODEL_ID='qwen2.5-coder-3b'
$env:NIBLIT_QWEN_PORT='8968'
$env:NIBLIT_N_GPU_LAYERS='0'
$env:NIBLIT_STORAGE_ROOT='D:\NiblitAIOS\data\android-cloud-preview'
New-Item -ItemType Directory -Force -Path $logs|Out-Null
$proc=Start-Process -FilePath $python -ArgumentList @('main.py') -WorkingDirectory $root -PassThru -RedirectStandardOutput "$logs\cloud-preview.stdout.log" -RedirectStandardError "$logs\cloud-preview.stderr.log"
Write-Output "Four-model Cloud preview launched PID $($proc.Id) at http://127.0.0.1:8212"
