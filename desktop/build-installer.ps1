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

& $dotnet run --project (Join-Path $desktop 'VolkaPortal.Desktop.Tests') -c Release
if ($LASTEXITCODE -ne 0) { throw 'URL policy tests failed.' }

& $dotnet publish $project -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o $publish
if ($LASTEXITCODE -ne 0) { throw 'Desktop publish failed.' }
$loader = Join-Path $desktop 'VolkaPortal.Desktop\bin\Release\net10.0-windows\win-x64\runtimes\win-x64\native\WebView2Loader.dll'
if (!(Test-Path -LiteralPath $loader)) { throw 'WebView2 native loader not found after publish.' }
Copy-Item -LiteralPath $loader -Destination (Join-Path $publish 'WebView2Loader.dll') -Force

if (!(Test-Path $runtime)) {
    Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $runtime
}
$signature = Get-AuthenticodeSignature $runtime
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
    throw 'WebView2 installer Microsoft signature is invalid.'
}

for ($attempt = 1; $attempt -le 3; $attempt++) {
    & $iscc "/DAppVersion=$version" (Join-Path $desktop 'installer.iss')
    if ($LASTEXITCODE -eq 0) { break }
    if ($attempt -eq 3) { throw 'Installer compilation failed.' }
    Start-Sleep -Seconds (2 * $attempt)
}

Get-FileHash $installer -Algorithm SHA256
