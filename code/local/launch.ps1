param(
    [ValidateSet('Start', 'Stop')][string]$Action = 'Start',
    [ValidateRange(1024, 65535)][int]$Port = 8000,
    [switch]$NoBrowser
)

# Windows PowerShell 5.1 compatible. No machine-wide policy or settings changes.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'project-env.ps1')
$runtimeDirectory = Join-Path $PSScriptRoot '.tmp/runtime'
[System.IO.Directory]::CreateDirectory($runtimeDirectory) | Out-Null
$statePath = Join-Path $runtimeDirectory "launcher-$Port.json"
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$url = "http://127.0.0.1:$Port/"
$launchLock = $null
$httpClient = $null
$startedProcess = $null

function Test-PaperTrailReady {
    try {
        $health = $httpClient.GetStringAsync("${url}api/health").GetAwaiter().GetResult() | ConvertFrom-Json
        if ($health.status -ne 'ok' -or 'arxiv' -notin $health.sources -or 'huggingface' -notin $health.sources) { return $false }
        $schema = $httpClient.GetStringAsync("${url}openapi.json").GetAwaiter().GetResult() | ConvertFrom-Json
        if ($schema.info.title -ne 'PaperTrail') { return $false }
        $homepage = $httpClient.GetStringAsync($url).GetAwaiter().GetResult()
        return $homepage.Contains('<title>PaperTrail')
    } catch { return $false }
}

function Stop-OwnedProcess([System.Diagnostics.Process]$Process) {
    # The venv launcher owns a child Python process. Stop this verified tree only.
    & (Join-Path $env:SystemRoot 'System32/taskkill.exe') /PID $Process.Id /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not stop launcher process $($Process.Id)." }
}

try {
    # Serialize repeated double-clicks in the same checkout and on the same port.
    $lockPath = Join-Path $runtimeDirectory "launcher-$Port.lock"
    for ($attempt = 0; $attempt -lt 200; $attempt++) {
        try {
            $launchLock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
            break
        } catch [System.IO.IOException] { Start-Sleep -Milliseconds 100 }
    }
    if ($null -eq $launchLock) { throw 'Another launcher is still working. Please try again shortly.' }

    if ($Action -eq 'Stop') {
        if (-not (Test-Path -LiteralPath $statePath)) { throw 'No service managed by this launcher. A terminal-started service must be stopped with Ctrl+C in its terminal.' }
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if ($state.project_root -ne $paperTrailRoot -or $state.port -ne $Port) { throw 'Launcher ownership record does not match this project.' }
        $ownedProcess = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
        if ($null -eq $ownedProcess) { Write-Output 'PaperTrail is already stopped.'; exit 0 }
        if ($ownedProcess.StartTime.ToUniversalTime().ToString('o') -ne $state.process_start_utc -or $ownedProcess.Path -ne $pythonPath) {
            throw 'Process identity changed. Refusing to stop an unrelated process.'
        }
        Stop-OwnedProcess $ownedProcess
        Write-Output 'PaperTrail stopped.'
        exit 0
    }

    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $httpClient = New-Object System.Net.Http.HttpClient($handler)
    $httpClient.Timeout = [TimeSpan]::FromSeconds(2)
    if (Test-PaperTrailReady) {
        Write-Output "PaperTrail is already running: $url"
    } else {
        $listening = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
        if (@($listening | Where-Object { $_.Port -eq $Port }).Count -gt 0) {
            throw "Port $Port is occupied but PaperTrail is not ready. No process was stopped."
        }
        if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python environment missing. Run setup.ps1 first.' }
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend/dist/index.html'))) { throw 'Web build missing. Run setup.ps1 first.' }

        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $stdoutPath = Join-Path $runtimeDirectory "launcher-$Port-$stamp.stdout.log"
        $stderrPath = Join-Path $runtimeDirectory "launcher-$Port-$stamp.stderr.log"
        $startedProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', "$Port", '--no-access-log') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
        $processStarted = $startedProcess.StartTime.ToUniversalTime().ToString('o')
        $ready = $false
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            if ($startedProcess.HasExited) { throw "PaperTrail exited. Check log: $stderrPath" }
            if (Test-PaperTrailReady) { $ready = $true; break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $ready) { throw "Startup could not be confirmed. Check log: $stderrPath" }
        [pscustomobject]@{
            pid = $startedProcess.Id
            process_start_utc = $processStarted
            project_root = $paperTrailRoot
            port = $Port
            stdout = $stdoutPath
            stderr = $stderrPath
        } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        # Startup is now complete; a browser launch failure should not kill the server.
        $startedProcess = $null
        Write-Output "PaperTrail is ready: $url"
    }
    if (-not $NoBrowser) { Start-Process -FilePath $url }
} catch {
    if ($null -ne $startedProcess -and -not $startedProcess.HasExited) {
        try { Stop-OwnedProcess $startedProcess } catch { Write-Warning 'Could not stop the failed startup process. See runtime logs.' }
    }
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($null -ne $httpClient) { $httpClient.Dispose() }
    if ($null -ne $launchLock) { $launchLock.Dispose() }
}
