; Branch -- Windows installer.
;
; WHY AN INSTALLER AND NOT JUST A ZIP. A zip asks somebody to extract a folder,
; keep it together, find one .exe among a folder of DLLs, and make their own
; shortcut. Every one of those is a place to get stuck, and the person this is
; built for got stuck. An installer is one file: double-click, Next, done, and
; Branch is in the Start menu like any other program.
;
; PER-USER, NOT PER-MACHINE. PrivilegesRequired=lowest installs into the user's
; own AppData, which means no "do you want to allow this app to make changes"
; prompt and no administrator password. Somebody installing a program a friend
; sent them should not have to type an admin password to do it.
;
; The zip is still published beside this, for anyone who would rather have a
; folder they can move about.

#define AppName      "Branch"
#define AppPublisher "paleLeap"
#define AppURL       "https://github.com/paleLeap/branch"
#define AppExe       "Branch.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B7A1C3E2-4D5F-4A6B-9C8D-1E2F3A4B5C6D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; No "which folder?" and no component tree. There is one program and one place
; for it; asking would only be a question he cannot answer.
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=Branch-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Shown before anything is installed, so the two things that actually trip
; people up are read before they can be forgotten.
InfoBeforeFile=START-HERE.txt
LicenseFile=LICENSE
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a Branch shortcut on my desktop"; \
    GroupDescription: "Shortcuts:"

[Files]
; The whole PyInstaller folder, _internal and all. recursesubdirs is what keeps
; the 200MB of Qt and Chromium with it -- Branch cannot start without them.
Source: "dist\Branch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Start here (read this first)"; Filename: "{app}\START-HERE.txt"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Offered, not forced, and unchecked-by-default would be worse: the first thing
; he should do is read the four minutes of instructions, then start it.
Filename: "{app}\START-HERE.txt"; Description: "Open the start guide"; \
    Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\{#AppExe}"; Description: "Start Branch now"; \
    Flags: postinstall nowait skipifsilent

[UninstallDelete]
; PyInstaller writes nothing back into its own folder, but Qt's browser leaves a
; cache under the install directory if it was ever pointed there. Leave nothing
; behind that the user did not put there themselves; their settings live in
; %APPDATA%\branch and are deliberately NOT removed -- uninstalling a program
; should not throw away the trades they tuned.
Type: filesandordirs; Name: "{app}\QtWebEngine"
