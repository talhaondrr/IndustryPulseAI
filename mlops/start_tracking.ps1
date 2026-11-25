$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv/Scripts/python.exe'
Push-Location $root
try {
    New-Item -ItemType Directory -Force '.mlflow/artifacts' | Out-Null
    & $python -m mlflow server --host 127.0.0.1 --port 5000 --workers 1 `
        --backend-store-uri 'sqlite:///.mlflow/tracking.db' `
        --serve-artifacts --artifacts-destination '.mlflow/artifacts'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}
