param([int]$DebounceSeconds = 8)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$hash = [System.Security.Cryptography.SHA256]::Create()
try {
    $key = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant()))).Replace('-', '')
} finally {
    $hash.Dispose()
}
$mutex = New-Object System.Threading.Mutex($false, "Local\VolkaPortalGraphify-$key")
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) {
        Write-Output 'Graphify is already watching this project.'
        exit 0
    }
    if ($DebounceSeconds -lt 1) { throw 'DebounceSeconds must be positive.' }
    $python = $env:GRAPHIFY_PYTHON
    if (-not $python -and (Get-Command uv -ErrorAction SilentlyContinue)) {
        $toolRoot = (& uv tool dir).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve uv tools directory.' }
        $python = Join-Path $toolRoot 'graphifyy\Scripts\python.exe'
    }
    if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'Set GRAPHIFY_PYTHON to the interpreter containing graphify and watchdog.'
    }
    & $python -c 'import graphify, watchdog'
    if ($LASTEXITCODE -ne 0) { throw 'Install watchdog into the Graphify tool environment first.' }
    Set-Location -LiteralPath $root
    $env:GRAPHIFY_MAX_WORKERS = '2'
    $env:PYTHONUNBUFFERED = '1'
    $env:PYTHONUTF8 = '1'
    if (-not (Test-Path -LiteralPath (Join-Path $root 'graphify-out\graph.json'))) {
        throw 'Run graphify extract . --code-only --no-cluster, then graphify cluster-only . --no-label first.'
    }
    & $python -m graphify.watch $root --debounce $DebounceSeconds
    if ($LASTEXITCODE -ne 0) { throw "Graphify watcher exited with code $LASTEXITCODE." }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
