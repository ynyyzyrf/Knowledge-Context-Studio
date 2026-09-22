param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (!$SkipBuild) {
    docker build --platform linux/amd64 -t kcs-platform:local .
    if ($LASTEXITCODE) { throw 'Platform build failed' }
}
$engineImage = 'sha256:de1a4377bdde45814ff92342735c2acfc6408b098dd78fac4048bc92519d817b'
$postgresImage = 'postgres@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685'
docker image inspect $engineImage --format '{{.Architecture}}'
if ($LASTEXITCODE) { throw 'Validated native engine image is missing on this machine.' }
docker tag $engineImage kcs-openviking:20ec78a1
if ($LASTEXITCODE) { throw 'Engine tagging failed' }
docker image inspect $postgresImage --format '{{.Architecture}}'
if ($LASTEXITCODE) { throw 'Pinned PostgreSQL image is missing; pull the digest from compose.deploy.yaml.' }
docker tag $postgresImage kcs-postgres:16-validated
if ($LASTEXITCODE) { throw 'PostgreSQL tagging failed' }
New-Item -ItemType Directory -Force -Path runtime/deploy | Out-Null
$archivePath = Join-Path (Get-Location) 'runtime/deploy/kcs-images.tar'
docker save --output $archivePath kcs-platform:local kcs-openviking:20ec78a1 kcs-postgres:16-validated
if ($LASTEXITCODE) { throw 'Image export failed' }
$checksum = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
"$checksum  kcs-images.tar" | Set-Content -Encoding ascii -LiteralPath runtime/deploy/kcs-images.tar.sha256
Write-Output 'Exported runtime/deploy/kcs-images.tar and checksum. No runtime configuration or database volumes included.'
