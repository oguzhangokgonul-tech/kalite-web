#define AppName "VolkaPortal"
#ifndef AppVersion
#define AppVersion "0.1.6"
#endif

[Setup]
AppId={{7F87E02C-FF43-49D5-A680-D2BC0D2628AE}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\VolkaPortal
DefaultGroupName=VolkaPortal
OutputDir=dist
OutputBaseFilename=VolkaPortal-Setup-{#AppVersion}-win-x64
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\app\static\brand\favicon\favicon.ico
UninstallDisplayIcon={app}\VolkaPortal.Desktop.exe
WizardStyle=modern
#ifdef SignedRelease
SignTool=volkaportal
SignedUninstaller=yes
#endif

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "dist\publish\VolkaPortal.Desktop.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\publish\WebView2Loader.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\VolkaPortal"; Filename: "{app}\VolkaPortal.Desktop.exe"
Name: "{group}\VolkaPortal Kaldır"; Filename: "{uninstallexe}"
Name: "{autodesktop}\VolkaPortal"; Filename: "{app}\VolkaPortal.Desktop.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Masaüstü kısayolu oluştur"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "WebView2 Runtime kontrol ediliyor..."; Flags: waituntilterminated
Filename: "{app}\VolkaPortal.Desktop.exe"; Description: "VolkaPortal'ı aç"; Flags: nowait postinstall skipifsilent
Filename: "{app}\VolkaPortal.Desktop.exe"; Flags: nowait skipifnotsilent; Check: IsAutoUpdate

[Code]
var
  MaintenancePage: TInputOptionWizardPage;
  ExistingUninstaller: String;
  MaintenanceFinished: Boolean;
  RemoveUserData: Boolean;
  AutoUpdateSucceeded: Boolean;

function HasArgument(const Argument: String): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
    if UpperCase(ParamStr(Index)) = UpperCase(Argument) then
    begin
      Result := True;
      Exit;
    end;
end;

function IsAutoUpdate: Boolean;
begin
  Result := HasArgument('/AUTOUPDATE');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
    AutoUpdateSucceeded := True;
end;

procedure DeinitializeSetup;
var
  ResultCode: Integer;
begin
  if IsAutoUpdate and not AutoUpdateSucceeded and
    FileExists(ExpandConstant('{app}\VolkaPortal.Desktop.exe')) then
  begin
    SaveStringToFile(ExpandConstant('{localappdata}\VolkaPortal\Updates\last-update-failure.txt'),
      'Kurulum tamamlanamadi', False);
    Exec(ExpandConstant('{app}\VolkaPortal.Desktop.exe'), '', '', SW_SHOWNORMAL,
      ewNoWait, ResultCode);
  end;
end;

procedure InitializeWizard;
var
  UninstallCommand: String;
begin
  if RegQueryStringValue(HKEY_CURRENT_USER,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7F87E02C-FF43-49D5-A680-D2BC0D2628AE}_is1',
    'UninstallString', UninstallCommand) then
    ExistingUninstaller := RemoveQuotes(UninstallCommand);

  MaintenancePage := CreateInputOptionPage(wpWelcome, 'VolkaPortal kurulu',
    'Bu bilgisayarda VolkaPortal zaten kurulu.',
    'Yapmak istediğiniz işlemi seçin:', True, False);
  MaintenancePage.Add('&Güncelle / Yeniden kur');
  MaintenancePage.Add('&Kaldır');
  MaintenancePage.SelectedValueIndex := 0;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = MaintenancePage.ID) and
    (not FileExists(ExistingUninstaller));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ResultCode: Integer;
  UninstallParams: String;
  UserDataDir: String;
begin
  Result := True;
  if (CurPageID <> MaintenancePage.ID) or
    (MaintenancePage.SelectedValueIndex <> 1) then
    Exit;

  Result := False;
  if MsgBox('VolkaPortal uygulamasını bu bilgisayardan kaldırmak istiyor musunuz?' + #13#10 +
    'Devam etmeden önce açık VolkaPortal pencerelerini kapatın.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;

  RemoveUserData := MsgBox(
    'Bu bilgisayardaki VolkaPortal oturum ve önbellek verileri de silinsin mi?' + #13#10 +
    'Sunucudaki şirket kayıtları ve indirilen dosyalar etkilenmez.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;

  UninstallParams := '/KEEPUSERDATA';
  if RemoveUserData then
    UninstallParams := '/REMOVEUSERDATA';

  if not Exec(ExistingUninstaller, UninstallParams, '', SW_SHOWNORMAL,
    ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox('Kaldırıcı başlatılamadı: ' + SysErrorMessage(ResultCode), mbError, MB_OK);
    Exit;
  end;
  if ResultCode <> 0 then
  begin
    MsgBox('Kaldırma tamamlanmadı. Uygulama veya dosyalar açık olabilir.', mbError, MB_OK);
    Exit;
  end;

  if RemoveUserData then
  begin
    UserDataDir := ExpandConstant('{localappdata}\VolkaPortal\WebView2');
    if DirExists(UserDataDir) and not DelTree(UserDataDir, True, True, True) then
      MsgBox('Uygulama kaldırıldı, ancak yerel oturum verileri silinemedi: ' +
        UserDataDir, mbError, MB_OK);
    RemoveDir(ExpandConstant('{localappdata}\VolkaPortal'));
  end;

  MaintenanceFinished := True;
  WizardForm.Close;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if MaintenanceFinished then
    Confirm := False;
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  RemoveUserData := HasArgument('/REMOVEUSERDATA');
  if not RemoveUserData and not HasArgument('/KEEPUSERDATA') and
    not UninstallSilent then
    RemoveUserData := MsgBox(
      'Bu bilgisayardaki VolkaPortal oturum ve önbellek verileri de silinsin mi?' + #13#10 +
      'Sunucudaki şirket kayıtları ve indirilen dosyalar etkilenmez.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: String;
begin
  if (CurUninstallStep <> usPostUninstall) or not RemoveUserData then
    Exit;

  UserDataDir := ExpandConstant('{localappdata}\VolkaPortal\WebView2');
  if DirExists(UserDataDir) and not DelTree(UserDataDir, True, True, True) then
  begin
    Log('Yerel oturum verileri silinemedi: ' + UserDataDir);
    if not UninstallSilent then
      MsgBox('Yerel oturum verileri silinemedi: ' + UserDataDir, mbError, MB_OK);
  end;
  RemoveDir(ExpandConstant('{localappdata}\VolkaPortal'));
end;
