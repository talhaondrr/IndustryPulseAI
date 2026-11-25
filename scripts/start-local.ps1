[CmdletBinding()]
param([switch]$Initialize)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv/Scripts/python.exe'
$dashboard = Join-Path $root 'dashboard/IndustryPulse.Web'
$state = Join-Path $root '.local'

function Invoke-Checked($program, [string[]]$arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "$program failed with exit code $LASTEXITCODE" }
}

function Test-Endpoint($url, $marker) {
    try {
        $response = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content -match $marker
    }
    catch { return $false }
}

function Start-Local($name, $port, $url, $marker, $file, [string[]]$arguments, $folder) {
    if (Test-Endpoint $url $marker) {
        Write-Host "$name is already available at $url."
        return
    }
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is occupied or $name failed its readiness check."
    }

    $process = Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $folder `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $state "$name.out.log") `
        -RedirectStandardError (Join-Path $state "$name.err.log")
    @{ id = $process.Id; started = $process.StartTime.ToUniversalTime().Ticks.ToString() } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $state "$name.json") -Encoding UTF8

    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        if ($process.HasExited) { break }
        if (Test-Endpoint $url $marker) { Write-Host "$name is ready at $url."; return }
        Start-Sleep -Seconds 1
    }
    throw "$name failed to become ready. See .local/$name.err.log."
}

Push-Location $root
try {
    if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath '.env')) {
        throw 'Create .venv and .env using the setup instructions in README.md.'
    }
    $dotnet = (Get-Command dotnet -ErrorAction Stop).Source
    $powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
    New-Item -ItemType Directory -Path $state -Force | Out-Null
    Invoke-Checked docker @('compose', '--profile', 'streaming', 'up', '-d', '--wait', 'postgres', 'kafka')
    Invoke-Checked docker @('compose', 'exec', '-T', 'kafka', '/opt/kafka/bin/kafka-topics.sh',
        '--bootstrap-server', 'kafka:29092', '--create', '--if-not-exists',
        '--topic', 'industrial-sensor-data', '--partitions', '1', '--replication-factor', '1')

    if ($Initialize) {
        Invoke-Checked $python @('-m', 'src.init_database')
        Invoke-Checked $python @('-m', 'pipelines.etl_pipeline')
        Invoke-Checked $python @('-c', 'from streaming.spark_streaming import ensure_schema; ensure_schema()')
    }
    Invoke-Checked $python @('-m', 'src.database')
    if (-not (Test-Path -LiteralPath 'models/xgboost_pipeline.joblib') -or
        -not (Test-Path -LiteralPath 'models/model_metadata.json')) {
        Invoke-Checked $python @('-m', 'src.export_model')
    }

    Start-Local 'fastapi' 8000 'http://127.0.0.1:8000/health' '"model":"ready"' $python `
        @('-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '8000') $root
    $trackingScript = '"' + (Join-Path $root 'mlops/start_tracking.ps1') + '"'
    Start-Local 'mlflow' 5000 'http://127.0.0.1:5000/health' '^OK$' $powershell `
        @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $trackingScript) $root
    if (-not (Test-Endpoint 'http://127.0.0.1:5080/' '<title>Overview')) {
        Invoke-Checked $dotnet @('build', 'dashboard/IndustryPulse.Web/IndustryPulse.Web.csproj', '-c', 'Release')
    }
    Start-Local 'dashboard' 5080 'http://127.0.0.1:5080/' '<title>Overview' $dotnet `
        @('bin/Release/net10.0/IndustryPulse.Web.dll') $dashboard
    Write-Host 'Run the optional Spark and model-registration commands from README.md.'
}
finally { Pop-Location }
