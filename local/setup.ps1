# Install locked project dependencies and build the local web UI.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'project-env.ps1')
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required. See README.md.' }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js and npm are required. See README.md.' }
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    Push-Location (Join-Path $PSScriptRoot 'frontend')
    try {
        npm ci --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    Write-Output 'PaperTrail is ready. Run .\start.ps1 to start the local service.'
} finally { Pop-Location }
