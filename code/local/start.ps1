param([ValidateRange(1024, 65535)][int]$Port = 8000)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'project-env.ps1')
$paperTrailPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $paperTrailPython)) { throw 'Project environment missing. Run .\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend/dist/index.html'))) { throw 'Web build missing. Run .\setup.ps1 first.' }
Push-Location $PSScriptRoot
try {
    Write-Output "PaperTrail: http://127.0.0.1:$Port (Ctrl+C to stop)"
    & $paperTrailPython -m uvicorn backend.app:app --host 127.0.0.1 --port $Port --no-access-log
    if ($LASTEXITCODE -ne 0) { throw 'PaperTrail stopped with an error. Check the port and logs above.' }
} finally { Pop-Location }
