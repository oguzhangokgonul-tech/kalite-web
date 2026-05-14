$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = 5001
$Python = Join-Path $Root "venv\Scripts\python.exe"
$ServerOut = Join-Path $Root "flask-server.out.log"
$ServerErr = Join-Path $Root "flask-server.err.log"
$TunnelOut = Join-Path $Root "tunnel.out.log"
$TunnelErr = Join-Path $Root "tunnel.err.log"

Set-Location $Root

if (-not (Test-Path -LiteralPath $Python)) {
    throw "venv\Scripts\python.exe bulunamadi. Once sanal ortami ve paketleri kurun."
}

if (-not $env:SECRET_KEY) {
    $env:SECRET_KEY = [guid]::NewGuid().ToString("N")
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
    Start-Process `
        -FilePath $Python `
        -ArgumentList @("-m", "flask", "--app", "run.py", "run", "--host", "0.0.0.0", "--port", "$Port") `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ServerOut `
        -RedirectStandardError $ServerErr
    Start-Sleep -Seconds 3
}

Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "ssh.exe" -and $_.CommandLine -like "*localhost.run*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (Test-Path -LiteralPath $TunnelOut) { Remove-Item -LiteralPath $TunnelOut -Force }
if (Test-Path -LiteralPath $TunnelErr) { Remove-Item -LiteralPath $TunnelErr -Force }

$RemoteSpec = "80:127.0.0.1:{0}" -f $Port
Start-Process `
    -FilePath "C:\Windows\System32\OpenSSH\ssh.exe" `
    -ArgumentList @("-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=60", "-R", $RemoteSpec, "nokey@localhost.run") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $TunnelOut `
    -RedirectStandardError $TunnelErr

Start-Sleep -Seconds 8

$TunnelText = Get-Content -Raw $TunnelOut -ErrorAction SilentlyContinue
$Match = [regex]::Match($TunnelText, "https://[a-z0-9]+\.lhr\.life")

if ($Match.Success) {
    Write-Host ""
    Write-Host "Paylasim linki:"
    Write-Host $Match.Value
    Write-Host ""
    Write-Host "Giris sayfasi:"
    Write-Host ($Match.Value + "/login")
} else {
    Write-Host "Tunnel linki bulunamadi. tunnel.err.log ve tunnel.out.log dosyalarini kontrol edin."
}
