param(
    [string]$SigningKey = (Join-Path $env:LOCALAPPDATA 'VolkaPortal\ReleaseSigning\desktop-update-named-p256.pem')
)

$ErrorActionPreference = 'Stop'
$desktop = $PSScriptRoot
$openssl = 'C:\AppServ\Apache24\bin\openssl.exe'
if (!(Test-Path -LiteralPath $openssl)) { $openssl = (Get-Command openssl -ErrorAction Stop).Source }
if (!(Test-Path -LiteralPath $SigningKey)) { throw 'Desktop update signing key not found.' }

$project = [xml](Get-Content -LiteralPath (Join-Path $desktop 'VolkaPortal.Desktop\VolkaPortal.Desktop.csproj'))
$version = [string]$project.Project.PropertyGroup.Version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid desktop version.' }
$filename = "VolkaPortal-Setup-$version-win-x64.exe"
$installer = Join-Path $desktop "dist\$filename"
if (!(Test-Path -LiteralPath $installer)) { throw 'Build the installer first.' }

$release = Join-Path $desktop 'dist\release'
New-Item -ItemType Directory -Path $release -Force | Out-Null
$payload = Join-Path $release 'latest.payload.tmp'
$signature = Join-Path $release 'latest.signature.tmp'
$publicDer = Join-Path $release 'latest.public.tmp'
try {
    & $openssl pkey -in $SigningKey -pubout -outform DER -out $publicDer
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read signing public key.' }
    $source = Get-Content -LiteralPath (Join-Path $desktop 'VolkaPortal.Desktop\UpdateClient.cs') -Raw
    $match = [regex]::Match($source, 'PublicKeyBase64 = "([^"]+)"')
    if (!$match.Success -or [Convert]::ToBase64String([IO.File]::ReadAllBytes($publicDer)) -ne $match.Groups[1].Value) {
        throw 'Signing key does not match the desktop client trust key.'
    }

    $sha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    $size = (Get-Item -LiteralPath $installer).Length
    $body = "$version`n$filename`n$sha256`n$size`n"
    [IO.File]::WriteAllText($payload, $body, (New-Object System.Text.UTF8Encoding($false)))
    & $openssl dgst -sha256 -sign $SigningKey -out $signature $payload
    if ($LASTEXITCODE -ne 0) { throw 'Manifest signing failed.' }

    $manifest = [ordered]@{
        version = $version
        filename = $filename
        sha256 = $sha256
        size = $size
        signature = [Convert]::ToBase64String([IO.File]::ReadAllBytes($signature))
    } | ConvertTo-Json -Compress
    Copy-Item -LiteralPath $installer -Destination (Join-Path $release $filename) -Force
    [IO.File]::WriteAllText((Join-Path $release 'latest.json'), $manifest,
        (New-Object System.Text.UTF8Encoding($false)))
    Write-Output "Release files prepared in $release"
    Write-Output "$filename SHA256 $sha256"
}
finally {
    foreach ($file in @($payload, $signature, $publicDer)) {
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    }
}
