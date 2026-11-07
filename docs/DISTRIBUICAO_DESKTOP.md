# Instalação, atualização e dados

Uma aplicação Python/FastAPI + Vue, com administrador gráfico Qt. O uso diário não exige terminal, Python, Node ou serviço Windows.

## Windows x64

Execute `EscrituraIntegrada-<versão>-windows-x64-setup.exe`. A instalação é por usuário em `%LOCALAPPDATA%\Programs\EscrituraIntegrada`. O identificador do aplicativo é estável entre versões. Execute o instalador novo para atualizar; não desinstale antes.

Encerre pelo menu **Sair** no tray após salvar o trabalho. O instalador recusa manutenção com a aplicação aberta. Não força o encerramento. Dados e configurações ficam por padrão em `%LOCALAPPDATA%\Codisplan\Escritura Integrada`, separados dos executáveis.

Antes de substituir a base, a manutenção verifica integridade, copia os arquivos e usa o backup consistente SQLite. As migrações são testadas em uma cópia; falhas restauram a anterior. Backups `.escritura-backup-*` ficam ao lado da pasta de dados. `maintenance-history` registra a atualização. A recuperação de manutenção interrompida está disponível no próximo instalador e na abertura gráfica, desde que não exista manutenção em execução. A reversão automática de dados não reinstala uma versão antiga dos executáveis.

O instalador detecta a versão instalada e recusa retrocesso SemVer. A desinstalação remove o programa e os atalhos, preservando os dados. A exclusão dos dados exige ação explícita posterior do usuário na pasta configurada.

### Migração do ZIP

As distribuições portáteis anteriores já usavam dados fora da pasta do programa; nesses casos escolha **Usar os dados atuais** no instalador. Se os dados estiverem em outro local, escolha **Migrar dados de uma pasta portátil diferente** e selecione a pasta que contém `escritura.sqlite3` (ou sua subpasta `data`). A seleção de pasta aparece somente na migração. A origem permanece intacta. A aplicação também oferece **Configurações → Migrar dados de uma pasta portátil**, com o motor parado. Uma base de destino preenchida não é mesclada nem substituída por outra silenciosamente.

## macOS

Pacotes separados para **Apple Silicon (arm64)** e **Intel (x64)**, com macOS **15.0 ou posterior** como mínimo declarado. Cada build e teste precisa executar no runner nativo correspondente. Não há afirmação de compatibilidade com versões anteriores nem uso de Rosetta.

Abra o `.pkg` da arquitetura do Mac. O Installer instala/atualiza `/Applications/Escritura Integrada.app`. Encerre o aplicativo pelo ícone da barra de menus antes de atualizar; processos abertos impedem a substituição. O mesmo bundle é atualizado e os dados ficam em `~/Library/Application Support/Codisplan/Escritura Integrada`, ou na pasta escolhida pelo usuário.

Na primeira abertura de uma base de versão anterior, um backup SQLite `backups/antes-schema-<n>-<data>.sqlite3` é concluído antes da migração transacional. Falha de migração não confirma alterações na base. Todos os usuários preservam seus perfis independentes. Arrastar o aplicativo para a Lixeira preserva os dados.

**Assinatura:** os bundles macOS possuem assinatura ad hoc de integridade; não há certificado Developer ID nem notarização Apple configurados. O instalador Windows não possui Authenticode configurado. Os testes nativos não comprovam a aprovação automática pelo Gatekeeper/SmartScreen de um download. Não desative as proteções do sistema. A publicação deve declarar essa limitação até existirem credenciais de assinatura.

## Operação

Fechar a janela mantém o aplicativo em segundo plano. **Abrir, Iniciar, Parar, Reiniciar, Configurações e Sair** estão no tray/barra de menus. É possível iniciar minimizado. O backup contém dados do escritório; mantenha as permissões da pasta e faça cópias externas conforme sua rotina.
