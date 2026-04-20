#define MyAppName "NotesAgentApp"
#ifndef MyAppVersion
  #define MyAppVersion "1.2"
#endif
#define MyAppPublisher "Notes Agent"
#define MyAppExeName "NotesAgentApp.exe"
#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "NotesAgentApp-Setup"
#endif
#ifndef SourceDir
  #define SourceDir "..\release\NotesAgentApp"
#endif

[Setup]
AppId={{A362AA09-0D02-4F8E-9D49-5D73F987A119}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release\installer
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
