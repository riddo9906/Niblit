param([switch]$SetupCollections)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $env:LOCALAPPDATA 'Niblit/memory-laboratory/.env'
$previousProfile = Join-Path $repoRoot '.env.memory-laboratory'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $envFile) | Out-Null
if (-not (Test-Path -LiteralPath $envFile) -and (Test-Path -LiteralPath $previousProfile)) {
    Copy-Item -LiteralPath $previousProfile -Destination $envFile
}
$compose = Join-Path $repoRoot 'deploy/memory-laboratory.compose.yml'
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerPath = if ($dockerCommand) { $dockerCommand.Source } else {
    Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
}
if (-not (Test-Path -LiteralPath $dockerPath)) { throw 'Docker Desktop CLI is not installed.' }
# Fresh desktop installations may not have refreshed this terminal's PATH.
$env:PATH = (Split-Path -Parent $dockerPath) + [System.IO.Path]::PathSeparator + $env:PATH
if (-not (Test-Path -LiteralPath $envFile)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $key = [System.BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
    $config = @(
        'QDRANT_URL=http://127.0.0.1:6333',
        "QDRANT_API_KEY=$key",
        'QDRANT_IMAGE=qdrant/qdrant:v1.18.0',
        'NIBLIT_MEMORY_COLLECTION_PREFIX=niblit_lab',
        'NIBLIT_MEMORY_EMBEDDING_MODEL=intfloat/multilingual-e5-small',
        'NIBLIT_MEMORY_EMBEDDING_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3',
        'NIBLIT_MEMORY_ALLOW_MODEL_DOWNLOAD=0',
        'NIBLIT_MEMORY_DISTANCE=Cosine'
    )
    [System.IO.File]::WriteAllLines($envFile, $config)
    Write-Host 'Created private local Qdrant configuration. Existing Core .env was preserved.'
}
& $dockerPath compose --project-name niblit-memory-lab --env-file $envFile -f $compose up -d
if ($LASTEXITCODE -ne 0) { throw 'Qdrant container could not start; check Docker Desktop.' }
if ($SetupCollections) {
    $python = Join-Path $repoRoot 'niblit-env/Scripts/python.exe'
    $packaged = Join-Path $repoRoot 'niblit.exe'
    Push-Location $repoRoot
    try {
        if (Test-Path -LiteralPath $packaged) {
            & $packaged --memory-lab --env-file $envFile --apply
        } elseif (Test-Path -LiteralPath $python) {
            & $python -m modules.memory_laboratory --env-file $envFile --apply
        } else { throw 'Core executable or Python dependencies are required.' }
        if ($LASTEXITCODE -ne 0) { throw 'Memory setup not ready. Rerun after Qdrant starts.' }
    } finally { Pop-Location }
}
Write-Host 'Qdrant uses loopback ports 6333/6334 and persistent named volume niblit_memory_qdrant.'
