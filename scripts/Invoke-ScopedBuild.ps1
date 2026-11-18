param(
    [string]$BuildRoot = 'D:\NiblitAIOS',
    [string]$BuildId = '',
    [ValidateSet('all','core','ui','cloud','lean','freqtrade')][string]$Component = 'all',
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'scoped-build.js'), '--root', $BuildRoot, '--component', $Component)
if ($BuildId) { $arguments += @('--id', $BuildId) }
if ($Execute) { $arguments += '--execute' } else { $arguments += '--plan' }
# The child receives scoped build settings; this shell's environment is unchanged.
& node @arguments
exit $LASTEXITCODE
