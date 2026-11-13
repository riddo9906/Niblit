param([Parameter(Mandatory=$true)][string]$Mt5Version)
$ErrorActionPreference = 'Stop'
if ($Mt5Version -notmatch '^5\.0\.\d+$') { throw 'Specify a reviewed exact MetaTrader5 package version.' }
$venv = Join-Path $PSScriptRoot '.venv'
if (Test-Path -LiteralPath $venv) { throw 'Use a fresh gateway project directory for installation.' }
py -3.12-64 -m venv $venv
if ($LASTEXITCODE) { throw '64-bit Python 3.12 environment creation failed.' }
$python = Join-Path $venv 'Scripts/python.exe'
& $python -m pip install --only-binary=:all: "MetaTrader5==$Mt5Version"
if ($LASTEXITCODE) { throw 'MetaTrader5 installation failed.' }
& $python -B -m unittest discover -s $PSScriptRoot -v
if ($LASTEXITCODE) { throw 'Gateway verification failed.' }
