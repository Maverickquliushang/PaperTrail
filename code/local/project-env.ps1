# Dot-source this file in each new PowerShell session.
# Changes apply only to the current process and its children.
$paperTrailRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
foreach ($paperTrailDirectory in @('.tmp', '.cache', 'output')) {
    [System.IO.Directory]::CreateDirectory(
        (Join-Path $paperTrailRoot $paperTrailDirectory)
    ) | Out-Null
}

$env:PAPERTRAIL_ROOT = $paperTrailRoot
$env:TEMP = Join-Path $paperTrailRoot '.tmp'
$env:TMP = $env:TEMP
$env:UV_CACHE_DIR = Join-Path $paperTrailRoot '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $paperTrailRoot '.cache/python'
$env:UV_PYTHON_DOWNLOADS = 'never'
$env:PIP_CACHE_DIR = Join-Path $paperTrailRoot '.cache/pip'
$env:npm_config_cache = Join-Path $paperTrailRoot '.cache/npm'
$env:PYTHONPYCACHEPREFIX = Join-Path $paperTrailRoot '.cache/pycache'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $paperTrailRoot '.cache/playwright'
