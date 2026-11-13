$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$expected=([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'base-image.id'))).Trim()
$observed=(docker image inspect niblit-client-cloud-portal:runtime-base-20261112 --format '{{.Id}}').Trim()
if($LASTEXITCODE -or $observed -ne $expected){throw 'Audited immutable base is unavailable or changed. Load the validated base archive; do not substitute latest.'}
Push-Location $repo
try {
 docker build --network=none --pull=false --provenance=false --build-arg SOURCE_DATE_EPOCH=1794441600 -f deploy/hybrid/Dockerfile -t niblit/portal:2026.11.12-hybrid1 .
 if($LASTEXITCODE){throw 'Hybrid image build failed'}
 docker compose -f deploy/hybrid/compose.yml --profile development config --quiet
 if($LASTEXITCODE){throw 'Compose configuration validation failed'}
} finally {Pop-Location}
