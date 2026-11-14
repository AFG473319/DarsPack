; DarsPack Inno Setup script (نصب‌کننده‌ی ویندوزی درس‌پک).
;
; What it does: wraps the PyInstaller onedir folder (dist\DarsPack)
; into a single setup.exe that installs the app for the current user
; (no admin needed), adds Start Menu (+ optional desktop) shortcuts
; and an entry in Settings > Apps for clean uninstall. The app's own
; library still defaults to ~/Documents/DarsPackLibrary — no change.
;
; Why a per-user install: classmates may not have admin rights, and the
; demo laptop has little free disk. Program Files + admin would be the
; "official" default, but per-user (%LocalAppData%\Programs\DarsPack)
; works for everyone and the app is fully portable anyway.
;
; Build: installer\build-installer.bat (needs Inno Setup 6 — see
; docs/dependencies.md). Output: dist\DarsPack-Setup.exe (gitignored).
; Bump AppVersion together with src/darspack/__init__.py __version__.
;
; [Setup]
; AppId is a stable GUID (generate once, never change after first
; release — it tells Windows "this is the same app" for upgrades).
#define MyAppName "DarsPack"
#define MyAppVersion "0.2.1"

[Setup]
AppId={{15da954e-9bf3-4804-85db-fe556307e417}
AppName=DarsPack
AppVersion=0.2.1
;VersionInfoVersion=0.2.1
AppPublisher=DarsPack
DefaultDirName={localappdata}\Programs\DarsPack
DefaultGroupName=DarsPack
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
OutputDir=..\dist
OutputBaseFilename=DarsPack-Setup
SetupIconFile=..\src\darspack\assets\icon\darspack.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=DarsPack
UninstallDisplayIcon={app}\DarsPack.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The whole onedir build (exe + _internal/). The wildcard copies the
; folder's contents into {app}, preserving _internal\*.
Source: "..\dist\DarsPack\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\DarsPack"; Filename: "{app}\DarsPack.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\DarsPack"; Filename: "{app}\DarsPack.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\DarsPack.exe"; Description: "Launch DarsPack"; Flags: nowait postinstall shellexec skipifsilent
