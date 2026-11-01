param([string]$ListenAddress = '127.0.0.1')
$ErrorActionPreference = 'Stop'
$portalRoot = Split-Path -Parent $PSScriptRoot
$serverExe = Join-Path $env:USERPROFILE 'llama_migration\llama.cpp\build\bin\Release\llama-server.exe'
$modelPath = Join-Path $env:USERPROFILE 'llama_migration\models\qwen2.5-coder-3b-instruct-q4_k_m.gguf'
$dataPath = Join-Path $portalRoot 'runtime\client-portal'
$keyPath = Join-Path $dataPath 'gguf-api-key'
if (!(Test-Path -LiteralPath $serverExe) -or !(Test-Path -LiteralPath $modelPath)) { throw 'Existing local GGUF runtime/model not found' }
$listener = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $ownerProcess = Get-Process -Id $listener[0].OwningProcess
    if ($ownerProcess.Path -ne $serverExe) { throw 'Port 8766 belongs to another service' }
    Write-Output 'The local GGUF service is already listening.'
    exit 0
}
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
if (!(Test-Path -LiteralPath $keyPath)) {
    $keyBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($keyBytes)
    [System.IO.File]::WriteAllText($keyPath,[Convert]::ToHexString($keyBytes))
}
# The key is read from an ignored private file, never command arguments or logs.
$serverArgs = @('-m', $modelPath, '--alias', 'qwen2.5-coder-3b', '--host', $ListenAddress,
    '--port', '8766', '--ctx-size', '4096', '--threads', '2', '--parallel', '1',
    '--gpu-layers', '0', '--api-key-file', $keyPath)
$modelProcess = Start-Process -FilePath $serverExe -ArgumentList $serverArgs -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $dataPath 'gguf.stdout.log') `
    -RedirectStandardError (Join-Path $dataPath 'gguf.stderr.log')
$modelProcess.PriorityClass = 'BelowNormal'
Write-Output ('Started existing local GGUF service, process ' + $modelProcess.Id + '. No model download or paid API request.')
