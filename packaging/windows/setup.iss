#define AppVersion "@@VERSION@@"
#define NumericVersion "@@NUMERIC@@"
#define PayloadDir "@@PAYLOAD@@"
#define HelperFile "@@HELPER@@"
#define OutputFolder "@@OUTPUT@@"
#define InstallerName "@@FILENAME@@"
[Setup]
AppId={{D596DE8F-DC39-47A6-B39C-41893D9184B5}
AppName=Escritura Integrada
AppVersion={#AppVersion}
AppPublisher=Codisplan
AppPublisherURL=https://github.com/codisplanfiscalai/escritura-integrada
DefaultDirName={localappdata}\Programs\EscrituraIntegrada
DefaultGroupName=Escritura Integrada
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputFolder}
OutputBaseFilename={#InstallerName}
SetupIconFile=@@ICON@@
UninstallDisplayIcon={app}\EscrituraIntegrada.exe
VersionInfoVersion={#NumericVersion}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
AppMutex=EscrituraIntegrada.Application
SetupMutex=EscrituraIntegrada.Setup
UsePreviousAppDir=yes
UsePreviousGroup=yes
DisableProgramGroupPage=yes
DisableDirPage=auto
Uninstallable=yes
[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#HelperFile}"; Flags: dontcopy
[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked
[Icons]
Name: "{group}\Escritura Integrada"; Filename: "{app}\EscrituraIntegrada.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Escritura Integrada"; Filename: "{app}\EscrituraIntegrada.exe"; WorkingDir: "{app}"; Tasks: desktopicon
[Run]
Filename: "{app}\EscrituraIntegrada.exe"; Description: "Abrir Escritura Integrada"; Flags: nowait postinstall skipifsilent
[Code]
function GetCurrentProcessId: LongWord;
  external 'GetCurrentProcessId@kernel32.dll stdcall';

var
  SourcePage: TInputDirWizardPage;
  Prepared, Completed: Boolean;
  PreviousVersion: String;

function ProfileDir: String;
begin
  Result := ExpandConstant('{param:PROFILEDIR|{localappdata}\Codisplan\Escritura Integrada}');
end;

function RunMaintenance(Action, Extra: String; var MessageText: String): Boolean;
var ExitCode: Integer; MessageFile, Arguments, Helper: String; TextAnsi: AnsiString;
begin
  ExtractTemporaryFile('EscrituraMaintenance.exe');
  Helper := ExpandConstant('{tmp}\EscrituraMaintenance.exe');
  MessageFile := ExpandConstant('{tmp}\escritura-maintenance-message.txt');
  DeleteFile(MessageFile);
  Arguments := Action + ' --owner-pid ' + IntToStr(GetCurrentProcessId) + ' --profile "' + ProfileDir + '" --version "{#AppVersion}" --message "' + MessageFile + '" ' + Extra;
  Result := Exec(Helper, Arguments, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0);
  if LoadStringFromFile(MessageFile, TextAnsi) then MessageText := UTF8Decode(TextAnsi)
  else MessageText := 'Não foi possível concluir a manutenção. A instalação foi interrompida antes de substituir os dados.';
end;

procedure InitializeWizard;
begin
  Prepared := False; Completed := False;
  RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{D596DE8F-DC39-47A6-B39C-41893D9184B5}_is1', 'DisplayVersion', PreviousVersion);
  SourcePage := CreateInputDirPage(wpSelectDir, 'Dados da aplicação', 'Instalar ou migrar a distribuição portátil',
    'A atualização preserva os dados e as configurações atuais. Para migrar uma pasta portátil diferente, selecione a pasta que contém escritura.sqlite3. Deixe vazio para usar a instalação atual ou iniciar uma base nova. Não é feita mesclagem de empresas.', False, '');
  SourcePage.Add('Pasta de dados portátil (opcional):');
  SourcePage.Values[0] := ExpandConstant('{param:PORTABLEDATA|}');
  if PreviousVersion <> '' then WizardForm.WelcomeLabel2.Caption :=
    'Versão instalada: ' + PreviousVersion + #13#10 + 'Nova versão: {#AppVersion}' + #13#10#13#10 +
    'Salve seu trabalho e encerre a aplicação pelo ícone da área de notificações. Os dados terão cópia de segurança e serão preservados.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = SourcePage.ID) and (SourcePage.Values[0] <> '') and not DirExists(SourcePage.Values[0]) then begin
    MsgBox('A pasta de dados selecionada não existe.', mbError, MB_OK); Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Extra, MessageText: String;
begin
  Result := '';
  if Prepared then Exit;
  if FileExists(ProfileDir + '\maintenance.json') then begin
    if not RunMaintenance('recover', '', MessageText) then begin Result := MessageText; Exit; end;
  end;
  Extra := '--previous-version "' + PreviousVersion + '"';
  if SourcePage.Values[0] <> '' then Extra := Extra + ' --source "' + SourcePage.Values[0] + '"';
  if not RunMaintenance('prepare', Extra, MessageText) then Result := MessageText
  else Prepared := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var MessageText: String;
begin
  if CurStep = ssPostInstall then begin
    if not RunMaintenance('finish', '', MessageText) then
      RaiseException('Não foi possível finalizar a atualização: ' + MessageText);
    Completed := True;
    WizardForm.FinishedLabel.Caption := 'Escritura Integrada {#AppVersion} instalada. Dados, empresas, usuários e permissões preservados. As cópias de segurança permanecem fora da pasta do programa. A desinstalação preserva os dados.';
  end;
end;

procedure DeinitializeSetup;
var MessageText: String;
begin
  if Prepared and not Completed then RunMaintenance('rollback', '', MessageText);
end;
