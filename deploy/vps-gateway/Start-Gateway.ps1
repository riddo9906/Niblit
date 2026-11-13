param(
    [Parameter(Mandatory=$true)][string]$Config,
    [Parameter(Mandatory=$true)][string]$StateDir
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
& $python -B (Join-Path $PSScriptRoot 'gateway.py') (Resolve-Path -LiteralPath $Config).Path (Resolve-Path -LiteralPath $StateDir).Path
exit $LASTEXITCODE
