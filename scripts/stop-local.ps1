[CmdletBinding()]
param([switch]$StopInfrastructure)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$state = Join-Path $root '.local'
Push-Location $root
try {
    foreach ($name in 'dashboard', 'mlflow', 'fastapi') {
        $file = Join-Path $state "$name.json"
        if (-not (Test-Path -LiteralPath $file)) { continue }
        $saved = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
        $target = Get-Process -Id $saved.id -ErrorAction SilentlyContinue
        if ($target -and $target.StartTime.ToUniversalTime().Ticks.ToString() -eq $saved.started) {
            & taskkill.exe /PID $saved.id /T /F
            if ($LASTEXITCODE -ne 0 -and (Get-Process -Id $saved.id -ErrorAction SilentlyContinue)) {
                throw "Unable to stop managed process $name."
            }
        }
        Remove-Item -LiteralPath $file
    }
    if ($StopInfrastructure) {
        docker compose --profile streaming stop kafka postgres
        if ($LASTEXITCODE -ne 0) { throw 'Docker Compose stop failed.' }
    }
    else { Write-Host 'Docker infrastructure is still available.' }
}
finally { Pop-Location }
