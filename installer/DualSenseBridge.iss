; Inno Setup script for DualSense Bridge
; Built by GitHub Actions (ci/release.yml) or locally by scripts\build.bat.
; Driver installers are optional: if build\drivers\ has them, they are bundled.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#define AppName "DualSense Bridge"
#define AppExe "DualSenseBridge.exe"
#define Root SourcePath + ".."
#define ViGEmPath Root + "\build\drivers\ViGEmBus_setup.exe"
#define HidHidePath Root + "\build\drivers\HidHide_setup.exe"

[Setup]
AppId={{8E7C2B5A-4D2F-4C8B-9B61-3F0D2E7A9C41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=flyingriverhorse
AppPublisherURL=https://github.com/flyingriverhorse/DualSenseBridge
AppSupportURL=https://github.com/flyingriverhorse/DualSenseBridge/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}\dist
OutputBaseFilename=DualSenseBridge-Setup
SetupIconFile={#Root}\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile={#Root}\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
#if FileExists(ViGEmPath)
Name: "vigem"; Description: "Install ViGEmBus driver (virtual Xbox controller) - required"; GroupDescription: "Drivers:"; Check: not ViGEmInstalled
#endif
#if FileExists(HidHidePath)
Name: "hidhide"; Description: "Install HidHide driver (hides the DualSense, no double input) - recommended, needs a restart"; GroupDescription: "Drivers:"; Check: not HidHideInstalled
#endif

[Files]
Source: "{#Root}\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\profiles.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
#if FileExists(ViGEmPath)
Source: "{#ViGEmPath}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: vigem
#endif
#if FileExists(HidHidePath)
Source: "{#HidHidePath}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: hidhide
#endif

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
#if FileExists(ViGEmPath)
Filename: "{tmp}\ViGEmBus_setup.exe"; StatusMsg: "Installing ViGEmBus..."; Flags: waituntilterminated; Tasks: vigem
#endif
#if FileExists(HidHidePath)
Filename: "{tmp}\HidHide_setup.exe"; StatusMsg: "Installing HidHide..."; Flags: waituntilterminated; Tasks: hidhide
#endif
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: postinstall nowait skipifsilent shellexec; Check: not RestartNeeded

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExe}"; Flags: runhidden; RunOnceId: "KillApp"
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn ""{#AppName}"" /f"; Flags: runhidden; RunOnceId: "RemoveAutostart"
Filename: "{commonpf64}\Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe"; Parameters: "--cloak-off"; Flags: runhidden skipifdoesntexist; RunOnceId: "CloakOff"

[Code]
function ViGEmInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\drivers\ViGEmBus.sys'));
end;

function HidHideInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\drivers\HidHide.sys'));
end;

function RestartNeeded(): Boolean;
begin
#if FileExists(HidHidePath)
  Result := WizardIsTaskSelected('hidhide');
#else
  Result := False;
#endif
end;

function NeedRestart(): Boolean;
begin
  Result := RestartNeeded();
end;

function ViGEmChosen(): Boolean;
begin
#if FileExists(ViGEmPath)
  Result := WizardIsTaskSelected('vigem');
#else
  Result := False;
#endif
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and (not ViGEmInstalled()) and (not ViGEmChosen()) then
    MsgBox('ViGEmBus is not installed. DualSense Bridge needs it for the virtual Xbox controller.' + #13#10 +
           'Download it from https://github.com/nefarius/ViGEmBus/releases', mbInformation, MB_OK);
end;
