$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = 5001

Set-Location $Root

Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "ssh.exe" -and $_.CommandLine -like "*localhost.run*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Write-Host "Paylasim durduruldu."
