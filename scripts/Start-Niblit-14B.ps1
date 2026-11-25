# Local Qwen 14B sidecar for Niblit. Does not modify demo trading or 3B inference.
[CmdletBinding()]
param(
  [int]$Port = 8967,
  [int]$Context = 2048,
  [int]$Threads = 4,
  [int]$GpuLayers = 0
)
$ErrorActionPreference = 'Stop'
$exe = 'C:\Users\Riyaad\llama_migration\llama.cpp\build\bin\Release\llama-server.exe'
$model = 'D:\Models\qwen2.5-coder-14b-instruct-q4_k_m.gguf'
$keyFile = 'D:\NiblitAIOS\config\trading-software-20261115\inference-key'
$logs = 'D:\NiblitAIOS\diagnostics\model-14b-20261120'
foreach ($path in @($exe, $model, $keyFile)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing model runtime component: $path" }
}
if ($Port -lt 1024 -or $Port -gt 65535 -or $Context -lt 512 -or $Threads -lt 1 -or $GpuLayers -lt 0) {
  throw 'Invalid local inference parameters'
}
$active = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($active) {
  $health = try { Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 3 } catch { $null }
  if ($health.status -eq 'ok') {
    Write-Output "Local model service on port $Port is already healthy; no duplicate started."
    return
  }
  throw "Port $Port is owned by another process."
}
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$args = @('-m', $model, '--host', '127.0.0.1', '--port', "$Port",
  '--ctx-size', "$Context", '--threads', "$Threads",
  '--n-gpu-layers', "$GpuLayers", '--parallel', '1',
  '--alias', 'qwen2.5-coder-14b', '--api-key-file', $keyFile)
$p = Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory (Split-Path $exe -Parent) -PassThru -RedirectStandardOutput (Join-Path $logs '14b.stdout.log') -RedirectStandardError (Join-Path $logs '14b.stderr.log')
Write-Output "Started Qwen2.5-Coder 14B at http://127.0.0.1:$Port (PID $($p.Id))."
