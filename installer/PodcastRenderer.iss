#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif

#define ProjectRoot AddBackslash(SourcePath) + ".."
#define AppName "Podcast Renderer"
#define AppExeName "PodcastRenderer.exe"

[Setup]
AppId={{7A5DA1E6-92B3-4E0E-9C7F-434E5A01CDA2}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=pereponkin
AppPublisherURL=https://github.com/pereponkin/PodcastRenderer
AppSupportURL=https://github.com/pereponkin/PodcastRenderer/issues
AppUpdatesURL=https://github.com/pereponkin/PodcastRenderer/releases
DefaultDirName={localappdata}\Programs\Podcast Renderer
DefaultGroupName=Podcast Renderer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=PodcastRenderer-Setup
SetupIconFile={#ProjectRoot}\assets\Podcast Renderer.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UseSetupLdr=x64
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=Podcast Renderer installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#ProjectRoot}\dist\PodcastRenderer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\FFMPEG_SOURCE_OFFER.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Podcast Renderer"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Podcast Renderer"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Podcast Renderer"; Flags: nowait postinstall skipifsilent
