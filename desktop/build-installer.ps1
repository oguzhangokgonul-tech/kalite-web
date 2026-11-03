param(
    [string]$CertificateThumbprint,
    [string]$TimestampUrl,
    [string]$ExpectedPublisherSubject,
    [string]$SignToolPath
)

$ErrorActionPreference = 'Stop'
$desktop = $PSScriptRoot
$dotnet = 'C:\Program Files\dotnet\dotnet.exe'
$iscc = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
if (!(Test-Path $iscc)) { $iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
$publish = Join-Path $desktop 'dist\publish'
$runtime = Join-Path $desktop 'dist\MicrosoftEdgeWebview2Setup.exe'
$project = Join-Path $desktop 'VolkaPortal.Desktop\VolkaPortal.Desktop.csproj'
$version = ([xml](Get-Content -LiteralPath $project)).Project.PropertyGroup.Version
$installer = Join-Path $desktop "dist\VolkaPortal-Setup-$version-win-x64.exe"

if (!(Test-Path $dotnet)) { throw '.NET 10 SDK not found.' }
if (!(Test-Path $iscc)) { throw 'Inno Setup 6 not found.' }
$signed = [bool]($CertificateThumbprint -or $TimestampUrl -or $ExpectedPublisherSubject -or $SignToolPath)
if ($signed) {
    if (!$CertificateThumbprint -or !$TimestampUrl -or !$ExpectedPublisherSubject) {
        throw 'Signed builds require CertificateThumbprint, TimestampUrl and ExpectedPublisherSubject.'
    }
    $CertificateThumbprint = $CertificateThumbprint -replace '\s', ''
    if ($CertificateThumbprint -notmatch '^[A-Fa-f0-9]{40}$') { throw 'Invalid certificate thumbprint.' }
    if ($TimestampUrl -notmatch '^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~/%-]*)?$') {
        throw 'Invalid RFC3161 timestamp URL.'
    }
    $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$CertificateThumbprint" -ErrorAction SilentlyContinue
    if (!$certificate -or !$certificate.HasPrivateKey -or $certificate.Subject -cne $ExpectedPublisherSubject) {
        throw 'Code-signing certificate is missing, has no private key, or has an unexpected publisher subject.'
    }
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

function Assert-VolkaSignature([string]$Path) {
    & $signtool verify /pa $Path
    if ($LASTEXITCODE -ne 0) { throw "Authenticode verification failed: $Path" }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or
        $signature.SignerCertificate.Thumbprint -ine $CertificateThumbprint -or
        $signature.SignerCertificate.Subject -cne $ExpectedPublisherSubject -or
        !$signature.TimeStamperCertificate) {
        throw "Unexpected publisher or missing RFC3161 timestamp: $Path"
    }
}

& $dotnet run --project (Join-Path $desktop 'VolkaPortal.Desktop.Tests') -c Release
if ($LASTEXITCODE -ne 0) { throw 'URL policy tests failed.' }

& $dotnet publish $project -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o $publish
if ($LASTEXITCODE -ne 0) { throw 'Desktop publish failed.' }
$loader = Join-Path $desktop 'VolkaPortal.Desktop\bin\Release\net10.0-windows\win-x64\runtimes\win-x64\native\WebView2Loader.dll'
if (!(Test-Path -LiteralPath $loader)) { throw 'WebView2 native loader not found after publish.' }
Copy-Item -LiteralPath $loader -Destination (Join-Path $publish 'WebView2Loader.dll') -Force
if ($signed) {
    $app = Join-Path $publish 'VolkaPortal.Desktop.exe'
    & $signtool sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $app
    if ($LASTEXITCODE -ne 0) { throw 'Desktop application signing failed.' }
    Assert-VolkaSignature $app
}

if (!(Test-Path $runtime)) {
    Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $runtime
}
$signature = Get-AuthenticodeSignature $runtime
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
    throw 'WebView2 installer Microsoft signature is invalid.'
}

for ($attempt = 1; $attempt -le 3; $attempt++) {
    $isccArgs = @("/DAppVersion=$version")
    if ($signed) {
        $signCommand = '$q{0}$q sign /sha1 {1} /fd SHA256 /tr {2} /td SHA256 $f' -f
            $signtool, $CertificateThumbprint, $TimestampUrl
        $isccArgs += '/DSignedRelease=1'
        $isccArgs += "/Svolkaportal=$signCommand"
    }
    & $iscc @isccArgs (Join-Path $desktop 'installer.iss')
    if ($LASTEXITCODE -eq 0) { break }
    if ($signed -or $attempt -eq 3) { throw 'Installer compilation failed.' }
    Start-Sleep -Seconds (2 * $attempt)
}

if ($signed) { Assert-VolkaSignature $installer }
else { Write-Warning 'Unsigned local build only; prepare-update-release.ps1 will reject it without -LocalTestOverride.' }

Get-FileHash $installer -Algorithm SHA256
