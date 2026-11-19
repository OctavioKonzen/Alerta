; Instalador do Alerta Roblox (Inno Setup 6)
; Gerado automaticamente pelo GitHub Actions (.github/workflows/instalador-pc.yml).
; Para gerar na mao: rode o PyInstaller (veja o workflow) e depois
;   iscc pc\instalador\AlertaRoblox.iss

#define AppNome "Alerta Roblox"
#define AppExe "AlertaRoblox.exe"
#define AppVersao GetEnv("APP_VERSION")
#if AppVersao == ""
  #define AppVersao "1.0.0"
#endif

[Setup]
AppId={{6F3C2B8E-4A1D-4C7B-9E2F-A17E5D0C9B41}
AppName={#AppNome}
AppVersion={#AppVersao}
AppPublisher=OctavioKonzen
DefaultDirName={autopf}\{#AppNome}
DefaultGroupName={#AppNome}
DisableProgramGroupPage=yes
; instala so para o usuario atual: nao pede administrador
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\saida
OutputBaseFilename=AlertaRoblox-Setup-{#AppVersao}
SetupIconFile=icone.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\AlertaRoblox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Alerta Roblox";               Filename: "{app}\{#AppExe}"
Name: "{group}\1 - Conectar minha conta";    Filename: "{app}\{#AppExe}"; Parameters: "conectar"
Name: "{group}\2 - Escolher area da tela";   Filename: "{app}\{#AppExe}"; Parameters: "setup"
Name: "{group}\3 - Enviar alerta de teste";  Filename: "{app}\{#AppExe}"; Parameters: "teste"
Name: "{group}\Ver jogador e servidor";      Filename: "{app}\{#AppExe}"; Parameters: "servidor"
Name: "{group}\Editar frases e opcoes";      Filename: "{app}\{#AppExe}"; Parameters: "configurar"
Name: "{group}\Modo debug (ver leitura)";    Filename: "{app}\{#AppExe}"; Parameters: "debug"
Name: "{group}\Desinstalar Alerta Roblox";   Filename: "{uninstallexe}"
Name: "{autodesktop}\Alerta Roblox";         Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "conectar"; Description: "Conectar minha conta do app agora"; Flags: postinstall nowait skipifsilent

[Messages]
ptbr.FinishedLabel=O Alerta Roblox foi instalado.%n%nPrimeiro use "Conectar minha conta" (mesmo e-mail e senha do app no celular). Depois abra o "Alerta Roblox" com o jogo aberto.
