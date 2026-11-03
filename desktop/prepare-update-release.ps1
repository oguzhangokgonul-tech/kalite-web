param(
    [string]$SigningKey = (Join-Path $env:LOCALAPPDATA 'VolkaPortal\ReleaseSigning\desktop-update-named-p256.pem'),
    [string]$CertificateThumbprint,
    [string]$ExpectedPublisherSubject,
    [string]$SignToolPath,
    [switch]$LocalTestOverride
)

$ErrorActionPreference = 'Stop'
$desktop = $PSScriptRoot
$openssl = 'C:\AppServ\Apache24\bin\openssl.exe'
if (!(Test-Path -LiteralPath $openssl)) { $openssl = (Get-Command openssl -ErrorAction Stop).Source }

$project = [xml](Get-Content -LiteralPath (Join-Path $desktop 'VolkaPortal.Desktop\VolkaPortal.Desktop.csproj'))
$version = [string]$project.Project.PropertyGroup.Version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid desktop version.' }
$filename = "VolkaPortal-Setup-$version-win-x64.exe"
$installer = Join-Path $desktop "dist\$filename"
if (!(Test-Path -LiteralPath $installer)) { throw 'Build the installer first.' }

if ($LocalTestOverride) {
    Write-Warning 'LOCAL TEST ONLY: Authenticode checks are bypassed. Do not distribute this release.'
} else {
    if (!$CertificateThumbprint -or !$ExpectedPublisherSubject) {
        throw 'Production release requires CertificateThumbprint and ExpectedPublisherSubject.'
    }
    $CertificateThumbprint = $CertificateThumbprint -replace '\s', ''
    if ($CertificateThumbprint -notmatch '^[A-Fa-f0-9]{40}$') { throw 'Invalid certificate thumbprint.' }
    if ($SignToolPath) {
        if (!(Test-Path -LiteralPath $SignToolPath -PathType Leaf)) { throw 'SignToolPath not found.' }
        $signtool = (Resolve-Path -LiteralPath $SignToolPath).Path
    } else {
        $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
        if ($command) { $signtool = $command.Source }
        else {
            $signtool = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
        }
        if (!$signtool) { throw 'Windows SDK signtool.exe not found; pass -SignToolPath.' }
    }
}
if (!(Test-Path -LiteralPath $SigningKey)) { throw 'Desktop update signing key not found.' }

function Assert-InstallerSignature([string]$Path) {
    & $signtool verify /pa $Path
    if ($LASTEXITCODE -ne 0) { throw 'Installer Authenticode verification failed.' }
    $authenticode = Get-AuthenticodeSignature -LiteralPath $Path
    if ($authenticode.Status -ne 'Valid' -or
        $authenticode.SignerCertificate.Thumbprint -ine $CertificateThumbprint -or
        $authenticode.SignerCertificate.Subject -cne $ExpectedPublisherSubject -or
        !$authenticode.TimeStamperCertificate) {
        throw 'Installer publisher or RFC3161 timestamp does not match the signed release.'
    }
}

$release = if ($LocalTestOverride) {
    Join-Path $desktop 'dist\local-test-release'
} else {
    Join-Path $desktop 'dist\release'
}
New-Item -ItemType Directory -Path $release -Force | Out-Null
$lock = [IO.File]::Open((Join-Path $release 'latest.publish.lock'),
    [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$temporaryName = "latest.$([guid]::NewGuid().ToString('N'))"
$payload = Join-Path $release "$temporaryName.payload.tmp"
$signature = Join-Path $release "$temporaryName.signature.tmp"
$publicDer = Join-Path $release "$temporaryName.public.tmp"
$manifestTemp = Join-Path $release "$temporaryName.json.tmp"
$manifestPath = Join-Path $release 'latest.json'
$releaseInstaller = Join-Path $release $filename
$copiedInstaller = $false
$activated = $false
try {
    $previousManifest = $null
    if (Test-Path -LiteralPath $manifestPath) {
        $previousManifest = Get-Content -LiteralPath $manifestPath -Raw
        $previous = $previousManifest | ConvertFrom-Json -ErrorAction Stop
        if (!$previous -or [string]$previous.version -notmatch '^\d+\.\d+\.\d+$') {
            throw 'Existing release manifest has an invalid version.'
        }
        $previousVersion = [version]::Parse([string]$previous.version)
        if ([version]::Parse($version) -le $previousVersion) {
            throw "Release version $version must be greater than existing version $previousVersion."
        }
        if ([string]$previous.filename -eq $filename) {
            throw 'New release must use a different installer filename.'
        }
    }
    if (Test-Path -LiteralPath $releaseInstaller) {
        throw 'New installer filename already exists in the release directory.'
    }

    & $openssl pkey -in $SigningKey -pubout -outform DER -out $publicDer
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read signing public key.' }
    $source = Get-Content -LiteralPath (Join-Path $desktop 'VolkaPortal.Desktop\UpdateClient.cs') -Raw
    $match = [regex]::Match($source, 'PublicKeyBase64 = "([^"]+)"')
    if (!$match.Success -or [Convert]::ToBase64String([IO.File]::ReadAllBytes($publicDer)) -ne $match.Groups[1].Value) {
        throw 'Signing key does not match the desktop client trust key.'
    }

    if (!$LocalTestOverride) { Assert-InstallerSignature $installer }
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
    [IO.File]::WriteAllText($manifestTemp, $manifest, (New-Object System.Text.UTF8Encoding($false)))

    $copiedInstaller = $true
    [IO.File]::Copy($installer, $releaseInstaller, $false)
    if ((Get-Item -LiteralPath $releaseInstaller).Length -ne $size -or
        (Get-FileHash -LiteralPath $releaseInstaller -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha256) {
        throw 'Copied installer does not match the signed manifest payload.'
    }
    if (!$LocalTestOverride) { Assert-InstallerSignature $releaseInstaller }

    $currentManifest = if (Test-Path -LiteralPath $manifestPath) {
        Get-Content -LiteralPath $manifestPath -Raw
    } else { $null }
    if ($currentManifest -cne $previousManifest) {
        throw 'Existing release manifest changed during preparation.'
    }
    if ($null -eq $previousManifest) {
        [IO.File]::Move($manifestTemp, $manifestPath)
    } else {
        [IO.File]::Replace($manifestTemp, $manifestPath, $null)
    }
    $activated = $true
    Write-Output "Release files prepared in $release"
    Write-Output "$filename SHA256 $sha256"
}
finally {
    try {
        if ($copiedInstaller -and !$activated) {
            $manifestReferencesCopy = $true
            if (Test-Path -LiteralPath $manifestPath) {
                try {
                    $current = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -ErrorAction Stop
                    $manifestReferencesCopy = [string]$current.filename -eq $filename
                } catch {
                    # Keep the copy when manifest state cannot be established safely.
                }
            } else {
                $manifestReferencesCopy = $false
            }
            if (!$manifestReferencesCopy -and (Test-Path -LiteralPath $releaseInstaller)) {
                Remove-Item -LiteralPath $releaseInstaller -Force
            }
        }
        foreach ($file in @($payload, $signature, $publicDer, $manifestTemp)) {
            if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
        }
    }
    finally {
        $lock.Dispose()
    }
}
