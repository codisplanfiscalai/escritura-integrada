# Aplicativo Windows — pacote portátil x64

## Abrir e trabalhar

Baixe o ZIP da versão aprovada, extraia **todo o conteúdo** e abra `EscrituraIntegrada/EscrituraIntegrada.exe` com duplo clique. Mantenha `_internal`, os avisos de terceiros e os demais arquivos na mesma pasta. Copiar somente o `.exe` não transporta o aplicativo completo.

O pacote inclui a janela Qt, o navegador integrado, a interface Vue compilada, a API e o runtime Python. O uso local não exige instalar Python, Node.js, um serviço Windows ou executar comandos. A abertura e as operações locais usam os recursos do próprio pacote; não há CDN ou compilação da interface na máquina do usuário.

É uma aplicação única: empresas, fiscal, contabilidade, financeiro e relatórios compartilham a mesma área de trabalho. Os processos `QtWebEngineProcess.exe` pertencem ao navegador integrado; não são programas separados por tela ou módulo.

**Arquitetura distribuída: Windows x64/AMD64.** O pacote é construído com Python 3.12 x64, PySide6 6.11.3 e PyInstaller 6.22.3. O PySide6 dessa versão disponibiliza wheels Windows AMD64 e ARM64, sem wheel `win32`; esta entrega não promete Windows de 32 bits nem produz um executável x86. O build x64 ocorre em Windows Server 2022 no GitHub Actions; compatibilidade com cada edição de Windows usada pelo escritório depende de validação nessa edição.

## Janela e área de notificações

| Comando | Funcionamento |
|---|---|
| Abrir | Exibe a mesma janela operacional |
| Iniciar | Abre a aplicação local quando está pausada |
| Parar | Aguarda as operações em andamento e mantém a administração acessível |
| Reiniciar | Conclui a parada e abre com a configuração salva |
| Configurações | Escolhe pasta de dados, porta local e início minimizado |
| Sair | Aguarda o encerramento do motor e fecha a aplicação |

Fechar a janela com **X** a oculta na área de notificações. Se o Windows não oferecer essa área, fechar solicita a saída. A opção **Iniciar minimizado** vale para a próxima abertura e não registra início automático com o Windows. Um erro de inicialização mostra uma mensagem na janela, mesmo com essa preferência ativa.

Um segundo duplo clique no executável traz a primeira janela à frente. `QLockFile` controla a instância do perfil e o IPC local solicita a abertura da janela já existente. Nenhum serviço Windows é instalado.

Parar, Reiniciar e Sair consultam o estado de edição da Vue. Havendo mudanças não salvas, a aplicação solicita descarte ou cancelamento. Fechar para a área de notificações conserva a edição.

### Registros e configurações

A janela de administração oferece **Abrir registros**. Os logs usam rotação em `logs/aplicacao.log` no perfil do usuário, incluindo diagnóstico do Qt e do navegador integrado. Mensagens do processo gráfico não dependem de uma janela de terminal.

O perfil fica em `QStandardPaths.AppLocalDataLocation`, com organização `Codisplan` e nome `Escritura Integrada`. A pasta exata aparece em Configurações. Ela contém `config.ini`, `data/`, armazenamento/cache do navegador e logs. O pacote portátil não contém banco de trabalho, credenciais, `config.ini` nem o perfil usado nos testes.

A pasta de dados é passada explicitamente à API, inclusive durante sua importação. Alterar a pasta em Configurações não move arquivos: abre os dados daquela pasta no próximo reinício. Use uma única instância gravando no mesmo SQLite. Para uma cópia manual dos dados, pare a aplicação e aguarde a conclusão antes de copiar o conjunto de arquivos da pasta.

A API escuta somente em `127.0.0.1`. A porta automática tenta conservar a última porta do perfil e seleciona outra livre quando necessário. Uma porta manual ocupada produz erro legível. O aplicativo não conecta sua interface a outro processo que esteja usando a porta.

## Relatórios e downloads

**Imprimir / PDF** utiliza uma página auxiliar interna `about:blank`, recebe o HTML do relatório e abre o diálogo nativo para salvar um PDF A4 paisagem. A página auxiliar recusa navegação externa e arquivos locais. Cancelar descarta a página temporária. A aplicação aguarda uma gravação em andamento antes de sair. CSVs e outros downloads do próprio aplicativo usam o diálogo nativo de salvamento.

O smoke automatizado abaixo cobre abertura e encerramento do pacote. Ele não confirma o diálogo nativo de PDF, impressão em papel, atalhos do tray ou todos os fluxos de escrituração. Essas interações continuam exigindo avaliação visual e funcional do aplicativo instalado no ambiente de uso.

## Construção e arquivos de entrega

Esta seção é destinada a quem mantém o projeto. O usuário final abre o executável por duplo clique.

No Windows, com Python 3.12 x64 e Node.js 22:

```powershell
py -3.12 -m venv .venv-desktop
.\.venv-desktop\Scripts\python.exe -m pip install -r requirements-desktop.txt
.\.venv-desktop\Scripts\python.exe scripts/build_windows.py --smoke
```

O CI recebe `frontend/dist` do job de validação e executa:

```powershell
python scripts/build_windows.py --skip-frontend --smoke
```

A construção confere os assets locais, o ícone, o cabeçalho PE AMD64, o subsistema gráfico sem console, DLLs Qt, o processo WebEngine, dados ICU, arquivos `.pak`, snapshot V8 e traduções. Usa o empacotamento `onedir` do PyInstaller com `console=False`. O ZIP inteiro é a unidade de distribuição.

| Arquivo em `artifacts/` | Conteúdo |
|---|---|
| `EscrituraIntegrada-<SemVer>-windows-x64.zip` | Pacote portátil completo |
| Mesmo nome com `.zip.sha256` | SHA-256 do ZIP, calculado em blocos |
| `windows-build.json` | Ferramentas, versão, validações PE/runtime, tamanho, hash, avisos e resultado do smoke |
| `windows-smoke.json` | Resultado supervisionado do binário extraído do ZIP |
| `windows-smoke-app.json` | Etapas incrementais registradas pelo próprio executável |
| `windows-smoke.png` | Captura da janela produzida pelo aplicativo |
| `windows-smoke-logs.log` | Registros do perfil temporário, quando produzidos |

A SemVer completa permanece em `VERSION`, na API, na interface e nos campos textuais do recurso Windows. O recurso numérico do Windows possui quatro componentes `uint16`; uma revisão de pré-lançamento acima de 65535 é limitada a esse valor somente nesse campo. `windows-build.json` informa o valor original e `revision_capped`. A identificação completa da versão e o nome do ZIP permanecem distintos.

O pacote não recebe assinatura de código neste processo. A ausência de assinatura e o resultado de um antivírus não devem ser confundidos com a validação funcional descrita abaixo.

## O que o smoke verifica

O teste extrai **o próprio ZIP gerado**, inicia seu `.exe` em um diretório de trabalho vazio e usa caminhos com espaços e caracteres Unicode. Remove variáveis de desenvolvimento que poderiam esconder dependências ausentes. Todos os dados são fictícios e ficam em uma pasta temporária isolada.

1. Cria o processo suspenso, associa-o a um **Windows Job Object** e só então permite a execução. O job acompanha os descendentes; fechar o handle encerra remanescentes mesmo se o supervisor falhar.
2. Aguarda a API do próprio executável e exige saúde, versão exata e demonstração habilitada no perfil temporário.
3. Espera a tela Vue, aciona o botão real de demonstração e exige a área de trabalho autenticada: empresa ativa, dez itens de navegação, conteúdo principal, versão, CSS e marca carregados. Uma tela vazia ou apenas a mensagem de carregamento não aprova.
4. Grava a captura da janela e solicita o encerramento. O desktop destrói as páginas antes do perfil WebEngine e confirma a parada do motor local.
5. Exige saída zero e contagem de processos do job igual a zero. Caso precise encerrar um filho à força, o resultado **falha**, mesmo que a API tenha respondido.

O runner desabilita somente a aceleração de GPU para esse teste. O sandbox do Chromium não é desabilitado pelo script. Um runner sem área de notificações não reprova apenas por essa ausência; o relatório registra a disponibilidade encontrada.

`windows-build.json` e `windows-smoke.json` registram o resultado de cada execução. A existência dos scripts e do workflow não comprova uma execução Windows: o aceite técnico depende dos artefatos de um job concluído com sucesso. Um screenshot deve ser revisto visualmente; esse smoke não substitui o teste dos fluxos empresariais.

## Componentes de terceiros

O pacote contém `THIRD_PARTY_NOTICES.txt`, `licenses/components.json` e os textos de licença/avisos disponíveis nos pacotes instalados. O coletor inclui PySide6, seus módulos Qt, Shiboken6, PyInstaller, as dependências Python aplicáveis e a licença Python quando presente na instalação de construção. O inventário informa componentes que não forneceram um arquivo de licença separado.

Os avisos de Vue, Lucide e dos demais pacotes frontend ficam em `_internal/frontend/dist/third-party/NOTICE.txt`, com inventário e textos em pastas adjacentes. O comando `npm run build` os coleta dos `node_modules` produzidos por `npm ci`, confere as versões no lockfile e registra os hashes dos arquivos copiados. Esse inventário inclui também pacotes de desenvolvimento e opcionais instalados; não afirma que todos eles estão no JavaScript final. O mesmo conteúdo acompanha a interface distribuída em Docker.

Qt WebEngine incorpora Chromium e componentes com licenças próprias. As fontes oficiais abaixo complementam os textos do pacote. Este inventário não atribui uma licença ao código da aplicação e não modifica as licenças de seus componentes.

## Referências oficiais

- [PySide6 6.11.3 — arquivos de distribuição](https://pypi.org/project/PySide6/6.11.3/#files).
- [PyInstaller 6.22.3 — arquivos de distribuição](https://pypi.org/project/pyinstaller/6.22.3/#files).
- [PyInstaller — uso, modo windowed e arquivos spec](https://pyinstaller.org/en/stable/usage.html).
- [PyInstaller — licença e exceção de distribuição](https://pyinstaller.org/en/stable/license.html).
- [Qt — licenciamento](https://www.qt.io/qt-licensing).
- [Qt for Python — licenças](https://doc.qt.io/qtforpython-6/licenses.html).
- [Qt WebEngine — licenças do Qt e Chromium](https://doc.qt.io/qt-6/qtwebengine-licensing.html).
- [Qt — repositórios de código](https://code.qt.io/cgit/qt/).
- [PySide — repositório de código](https://code.qt.io/cgit/pyside/pyside-setup.git/).
- [Microsoft — Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
- [Microsoft — nested jobs](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs).
- [Python — licença e direitos de terceiros](https://docs.python.org/3/license.html).
