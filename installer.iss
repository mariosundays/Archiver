; Archiver -- Windows installer.
; Version is passed in by build.bat / CI so it can never drift from
; core/__init__.VERSION:  ISCC.exe /DMyAppVersion=0.6.5 installer.iss
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName      "Archiver"
#define MyAppPublisher "Mario Domingos"
#define MyAppExeName   "Archiver.exe"
#define MyAppURL       "https://github.com/mariosundays/Archiver"
#define DistDir        "dist\Archiver"

[Setup]
AppId={{9E4C7A2B-6D81-4F35-A0C7-52B8E1F94D63}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_out
OutputBaseFilename=Archiver_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=LICENSE
; Installs per-user by default, so no admin prompt. Someone testing a beta
; should not have to hand it administrator rights.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; Everything PyInstaller produced, including app\resources\icon.ico.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Start {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent
