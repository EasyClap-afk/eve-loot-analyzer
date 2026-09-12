#ifndef AppVersion
  #define AppVersion "1.5"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist-v1.5\EveLootAnalyzer"
#endif

[Setup]
AppId={{E1C9CF31-22A2-45B4-8EB4-606DA3C70821}
AppName=EVE Loot Analyzer
AppVersion={#AppVersion}
AppPublisher=EasyClap-afk
AppPublisherURL=https://github.com/EasyClap-afk/eve-loot-analyzer
AppSupportURL=https://github.com/EasyClap-afk/eve-loot-analyzer/issues
DefaultDirName={localappdata}\Programs\EveLootAnalyzer
DefaultGroupName=EVE Loot Analyzer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist-v1.5
OutputBaseFilename=EveLootAnalyzer-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayIcon={app}\EveLootAnalyzer.exe
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\EVE Loot Analyzer"; Filename: "{app}\EveLootAnalyzer.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\EVE Loot Analyzer"; Filename: "{app}\EveLootAnalyzer.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\EveLootAnalyzer.exe"; Description: "{cm:LaunchProgram,EVE Loot Analyzer}"; Flags: nowait postinstall skipifsilent

; User data in LOCALAPPDATA\EveLootAnalyzer is intentionally not installed
; or removed here. Updates and uninstall preserve profiles and sessions.
