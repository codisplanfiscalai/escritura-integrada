# Backups remotos — incremento local

> Detalhes dos ensaios de tamanho, limpeza gerenciada, protocolos por blocos e camada Windows: [backup-reliability.md](backup-reliability.md).


A aplicação continua usando `Database`, SQLite/WAL, FastAPI e Vue. `stored_files.content` é a fonte canônica dos originais; `companies/...` é cache regenerável (`app/file_store.py`). Não há alteração do caminho operacional, migração PostgreSQL, Compose ou Docker. O menu administrativo **Backups remotos** é independente de **Arquivos e backup**, que continua disponível.

## Escopo e operação

Um destino ativo por instalação: Dropbox, Google Drive, S3 ou MinIO. O administrador configura provedor, pasta/bucket, referência externa de credencial e intervalo de 1–8760 horas. Configuração, fila, identidade do solicitante, destino de cada execução, checksums e histórico ficam em `data_dir/backup-control/state.sqlite3`. Nenhum token é aceito pela API de configuração. Todas as rotas exigem administrador; mutações usam o CSRF e controle de origem existentes. Demonstração não inicia o worker.

O worker consulta a fila a cada cinco segundos. Agenda em segundos UTC; a tela apresenta datas no fuso do navegador. A primeira execução agendada ocorre um intervalo após salvar. Depois de reinício, intervalos vencidos são agrupados em uma execução, e o próximo horário é calculado a partir da admissão. O processo precisa estar ligado. Alterar a configuração reinicia o próximo horário. Backups manuais não mudam o horário agendado.

Uma transação `BEGIN IMMEDIATE` e índice único parcial impedem duas solicitações ativas. Uma chave de idempotência persistente retorna a mesma solicitação, inclusive depois de falha. O bloqueio de arquivo do sistema operacional é mantido durante cópia/verificação/envio e liberado em caso de morte do processo. Processos no **mesmo host e volume local** cooperam pelo mesmo bloqueio. Não é solução de liderança distribuída: réplicas com volumes separados, NFS/SMB ou hosts diferentes não são suportadas. Não execute múltiplos escritores sobre cópias distintas do mesmo banco.

O snapshot usa a API SQLite online backup, incluindo transações confirmadas no WAL. Não copia o `.sqlite3` bruto nem WAL/SHM em uso. O snapshot é saneado (sessões/contextos e tentativas de login removidos, `secure_delete` e `VACUUM`) e validado com `integrity_check` e `foreign_key_check`. O ZIP contém apenas `escritura.sqlite3` e `manifest.json` versionado com tamanho e SHA-256. O pacote é extraído e validado localmente antes do envio. O histórico guarda também o SHA-256 externo do envelope cifrado.

## Proteção atual

Novos backups são envelopes `.eibk` autenticados com AES-256-GCM; consulte [chaves, criptografia e recuperação](backup-crypto.md). O ZIP descrito abaixo é o conteúdo interno cifrado e o formato legado. O identificador de chave é configurado na tela; chaves ficam em chaveiro externo ao diretório de dados.

## Credenciais e ativação real

**Não houve homologação em contas reais.** É necessário provisionar a conta, aplicativo OAuth, permissões e segredo fora do repositório. A tela recebe apenas uma referência, por exemplo `ESCRITURA_BACKUP_PRIMARY`. Essa variável, no ambiente do processo, contém JSON de um dos formatos abaixo (nomes de campo, sem valores reais):

- Dropbox/Drive: `access_token` para testes de curta duração; ou `refresh_token`, `client_id`, `client_secret` para renovação em cada upload. O consentimento inicial, redirect URI e obtenção do refresh token são externos. Não existe botão OAuth fictício na aplicação.
- S3/MinIO: `access_key_id`, `secret_access_key`, opcional `session_token`. Permissão de `PutObject` apenas no bucket/prefixo necessário e `GetObject` para confirmação por HEAD quando faltar checksum no PUT; sem permissão de exclusão. SSE-KMS pode exigir permissões adicionais de KMS. S3 usa endpoint regional AWS padrão; MinIO exige endpoint HTTPS e certificado confiável. Certificado autoassinado exige configurar a cadeia confiável no ambiente; TLS não é desabilitado.

Dropbox requer `files.content.write` e pasta acessível à aplicação. Drive requer Drive API habilitada, pasta identificada pelo ID e permissão de criação; escopo `drive.file` quando a pasta foi autorizada para esse aplicativo, ou escopo mais amplo somente se justificado na configuração OAuth externa. Esta versão não implementa service-account JWT nem autorização de equipe Dropbox.

Use mecanismo seguro de injeção de variáveis e restrinja acesso à inspeção do processo/container. Não coloque valores em comandos gravados no histórico, logs, `.env` versionado ou formulários da aplicação. Credenciais não são persistidas no banco de controle nem no pacote. Não há chave de criptografia no backup: **novos pacotes são cifrados e autenticados**. O chaveiro externo e os temporários locais exigem proteção independente; consulte `backup-crypto.md`. Proteja disco e destino com controle de acesso e criptografia de armazenamento. O SQLite inclui dados fiscais e hashes de senha dos usuários; não é um arquivo público.

Diretórios externos, `.env`, certificados e configurações do host não são percorridos. Originais com extensões conhecidas de segredo/certificado ou marcadores PEM provocam recusa do backup. Isso não é um classificador universal: não guarde segredos arbitrários ou certificados disfarçados/aninhados em anexos fiscais. Campos livres e arquivos de usuário precisam da governança normal de dados.

## Contratos e limites

- Dropbox: `/2/files/upload` até 150 MiB, sessões sequenciais acima disso; criação estrita, sem sobrescrita/autorename; confirma tamanho e `content_hash` do Dropbox.
- Drive: inicia sessão resumable e envia blocos de 8 MiB, conferindo ACK/ranges; valida host da URL antes de transmitir token; confirma tamanho e MD5 retornados. Não retoma uploads após queda nesta etapa.
- S3/MinIO: PUT único com assinatura AWS SigV4, `If-None-Match: *` e SHA-256 que o servidor valida e retorna. Sem checksum na resposta do PUT, confirma por HEAD assinado com tamanho/checksum; sem essa prova resulta em estado incerto, nunca em sucesso presumido.
- HTTPS sem redirects e sem repetição automática; timeout de 60 segundos por operação de socket. Nomes remotos incluem UUID da execução.
- Máximo 512 MiB no envelope cifrado e 2 GiB de SQLite; até cinco minutos para a cópia online do SQLite. Não há multipart S3, retomada persistente das sessões Dropbox/Drive ou rotação automática de secrets.
- Não é snapshot do SO, infraestrutura, PostgreSQL, Redis ou diretórios arbitrários. Outros artefatos necessários a cada implantação (configuração, certificados, secrets e ambiente) exigem proteção independente.

Fontes primárias consultadas: [Dropbox upload](https://docs.dropboxapi.com/dropbox-api/api-reference/user-endpoints/files/upload), [Dropbox OAuth](https://docs.dropboxapi.com/dropbox-api/docs/oauth), [Drive upload](https://developers.google.com/workspace/drive/api/guides/manage-uploads), [Google OAuth offline](https://developers.google.com/identity/protocols/oauth2/web-server#offline), [S3 PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html). O adaptador MinIO usa o contrato S3; compatibilidade de uma versão/instalação específica ainda precisa ser validada.

## Falhas, permissões e retenção

Cancelar funciona na fila ou durante snapshot/verificação; a transição para envio é serializada com o pedido de cancelamento. Depois de iniciar envio, cancelamento é recusado porque interromper o cliente não prova ausência do objeto remoto. Falha de comunicação ou checksum remoto divergente fica `uncertain`. Processo morto durante snapshot/envio fica `interrupted` ao adquirir novamente o bloqueio. Nunca há reenvio automático dessa intenção. Consulte o destino antes de solicitar um novo backup. Agenda pode criar uma nova execução no próximo intervalo, com outra identidade.

Nenhum backup local/remoto é removido automaticamente. Temporários próprios marcados são removidos após falha normal e no próximo tick após queda, sob o bloqueio do worker. Diretórios desconhecidos e restaurações interrompidas são preservados; falha de limpeza é reportada e exige inspeção local. A remoção é lógica; monitore espaço. A retenção deve ser definida externamente até existir uma política revisada de remoção. Erros exibidos não incorporam mensagens/respostas brutas do provedor.

Arquivos novos são `0600`, diretórios privados `0700`, pertencentes ao usuário efetivo do processo. O código não executa `chown` nem muda o proprietário do banco operacional. Em Docker, executar com UID/GID **10001:10001** e conservar `./data/app:/data`; não gerar a cópia como root e depois usá-la diretamente como banco da aplicação. Reserve espaço para snapshot, ZIP e cópia de verificação/extração. A implantação e os mounts existentes não foram alterados.

## Restauração

A tela autentica novos envelopes, valida e extrai o arquivo local da execução em `data_dir/backup-control/restores/<id>/escritura.sqlite3`. O diretório deve ser novo; repetição retorna conflito. Checksum externo, manifesto, limites, inventário, checksum interno e integridade SQLite são verificados. Extração explícita de dois membros, sem `extractall`, sem caminhos arbitrários, symlinks ou sobrescrita. Em erro, somente os arquivos criados nessa tentativa são removidos.

Para ZIP legado obtido externamente (novos `.eibk` usam o comando de `backup-crypto.md`), use em ambiente isolado, como o mesmo usuário não privilegiado que utilizará a cópia:

```sh
python -m app.backup_archive /caminho/copia.zip /caminho/novo-destino --sha256 CHECKSUM_DO_HISTORICO
```

A pasta pai precisa existir. Guarde o checksum externo separadamente do arquivo: checksums detectam corrupção, mas não são assinatura contra adulteração de arquivo e manifesto juntos. A aplicação nunca ativa a cópia, substitui o banco em produção, religa container ou promete rollback. Faça teste de abertura com versão compatível, reconstrua caches através da aplicação e valide fiscal/contabilmente antes de planejar qualquer cutover separado. Sessões precisam de novo login; usuários e hashes de senha permanecem.

## Verificações reproduzíveis

```sh
python -m unittest tests.test_backups -v
node --test frontend/tests/backups.test.js
npm ci --prefix frontend
npm run build --prefix frontend
python scripts/browser_backups.py
python -m scripts.ci.checks --version VERSAO_DO_CHECKOUT --source-sha COMMIT_LOCAL
```

Os testes criam SQLite temporário, usam somente credenciais sintéticas, simulam os quatro transportes e não enviam nada à nuvem. O teste Chromium inicia servidor temporário com uploader substituído apenas no processo de teste. `ESCRITURA_TEST_BROWSER` permite informar um Chromium instalado.
