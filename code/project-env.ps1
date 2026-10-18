$publicationRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$env:PYTHONUTF8 = '1'
$OutputEncoding = [System.Text.UTF8Encoding]::new()
foreach ($directory in @('.tmp', '.cache')) {
    [IO.Directory]::CreateDirectory((Join-Path $publicationRoot $directory)) | Out-Null
}
$env:TEMP = Join-Path $publicationRoot '.tmp'
$env:TMP = $env:TEMP
$env:UV_CACHE_DIR = Join-Path $publicationRoot '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $publicationRoot '.cache/python'
$env:UV_PYTHON_DOWNLOADS = 'never'
$env:PIP_CACHE_DIR = Join-Path $publicationRoot '.cache/pip'
$env:npm_config_cache = Join-Path $publicationRoot '.cache/npm'
$env:PYTHONPYCACHEPREFIX = Join-Path $publicationRoot '.cache/pycache'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $publicationRoot '.cache/playwright'
