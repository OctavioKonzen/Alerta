; Instalador do Alerta Roblox (Inno Setup 6)
; Gerado automaticamente pelo GitHub Actions (.github/workflows/instalador-pc.yml).
; Para gerar na mao: compile com o Nuitka (veja o workflow) e depois
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
VersionInfoVersion={#AppVersao}
VersionInfoCompany=OctavioKonzen
VersionInfoDescription=Instalador do Alerta Roblox
VersionInfoProductName=Alerta Roblox
VersionInfoCopyright=OctavioKonzen
AppPublisherURL=https://octaviokonzen.github.io/Alerta/
AppSupportURL=https://octaviokonzen.github.io/Alerta/
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
Name: "iniciarwindows"; Description: "Abrir o Alerta Roblox junto com o Windows"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\AlertaRoblox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Atalhos da versao antiga (com janela preta) que nao existem mais
[InstallDelete]
Type: files; Name: "{group}\1 - Conectar minha conta.lnk"
Type: files; Name: "{group}\2 - Escolher area da tela.lnk"
Type: files; Name: "{group}\3 - Enviar alerta de teste.lnk"
Type: files; Name: "{group}\Ver jogador e servidor.lnk"
Type: files; Name: "{group}\Editar frases e opcoes.lnk"
Type: files; Name: "{group}\Modo debug (ver leitura).lnk"

[Icons]
Name: "{group}\Alerta Roblox";               Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar Alerta Roblox";   Filename: "{uninstallexe}"
Name: "{autodesktop}\Alerta Roblox";         Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\Alerta Roblox";         Filename: "{app}\{#AppExe}"; Tasks: iniciarwindows

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o Alerta Roblox agora"; Flags: postinstall nowait skipifsilent
; Atualizacao automatica (instalacao silenciosa): reabre o programa sozinho
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent

[Messages]
ptbr.FinishedLabel=O Alerta Roblox foi instalado.%n%nNa janela dele: 1) Conectar com Discord; 2) Escolher area da tela; 3) Canal do Discord. Depois ele fica rodando perto do relogio do Windows.
