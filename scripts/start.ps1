param([switch]$Restart, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (!(Test-Path -LiteralPath '.env')) { throw 'Missing .env. Run local configuration setup first.' }
    uv sync --frozen
    if ($LASTEXITCODE) { throw 'Python dependency installation failed' }
    if (!$SkipBuild) {
        Push-Location (Join-Path $projectRoot 'web')
        try {
            npm ci
            if ($LASTEXITCODE) { throw 'Frontend dependency installation failed' }
            npm run build
            if ($LASTEXITCODE) { throw 'Frontend build failed' }
        } finally { Pop-Location }
    }
    if (!(Test-Path -LiteralPath 'web/dist/index.html')) { throw 'Frontend build is missing; rerun without -SkipBuild.' }
    docker compose up -d --wait postgres
    if ($LASTEXITCODE) { throw 'Database startup failed' }
    uv run alembic upgrade head
    if ($LASTEXITCODE) { throw 'Migration failed' }
    $runtimeDir = Join-Path $projectRoot 'runtime'
    $processFile = Join-Path $runtimeDir 'processes.json'
    $existing = if (Test-Path -LiteralPath $processFile) { Get-Content -LiteralPath $processFile | ConvertFrom-Json } else { $null }
    $states = @{}
    foreach ($kind in @('api','worker')) {
        $recordedPid = if ($existing) { $existing."${kind}_pid" } else { $null }
        $process = if ($recordedPid) { Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid" } else { $null }
        $expectedModule = if ($kind -eq 'api') { 'kcs.app:create_app' } else { 'kcs.worker' }
        $ours = $process -and $process.CommandLine.Contains($projectRoot) -and $process.CommandLine.Contains($expectedModule)
        if ($ours -and $Restart) {
            taskkill /PID $recordedPid /T /F | Out-Null
            if ($LASTEXITCODE) { throw "Could not stop project $kind process" }
            $ours = $false
        }
        if ($ours) { $states[$kind] = $recordedPid }
    }
    if (!$states['api'] -and (Get-NetTCPConnection -LocalPort 8088 -State Listen -ErrorAction SilentlyContinue)) {
        throw 'Port 8088 is occupied by an unrecognized process; not stopping it.'
    }
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    foreach ($kind in @('api','worker')) {
        if ($states[$kind]) { continue }
        $arguments = if ($kind -eq 'api') { @('-m','uvicorn','kcs.app:create_app','--factory','--host','127.0.0.1','--port','8088') } else { @('-m','kcs.worker') }
        $started = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir "$kind.stdout.log") -RedirectStandardError (Join-Path $runtimeDir "$kind.stderr.log") -PassThru
        $states[$kind] = $started.Id
    }
    @{api_pid=$states['api'];worker_pid=$states['worker']} | ConvertTo-Json | Set-Content -LiteralPath $processFile
    $ready = $false
    $readinessError = 'No healthy response'
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8088/health/ready' -TimeoutSec 2 -NoProxy
            $page = Invoke-WebRequest -Uri 'http://127.0.0.1:8088/' -TimeoutSec 2 -NoProxy
            if ($health.status -eq 'ok' -and $page.StatusCode -eq 200) { $ready = $true; break }
        } catch { $readinessError = $_.Exception.Message; Start-Sleep -Milliseconds 500 }
    }
    if (!$ready) { throw "API or frontend failed readiness check: $readinessError" }
    if (!(Get-Process -Id $states['worker'] -ErrorAction SilentlyContinue)) { throw 'Worker exited; inspect runtime/worker.stderr.log.' }
    Write-Output 'API/database and frontend ready; worker running: http://localhost:8088'
} finally { Pop-Location }
