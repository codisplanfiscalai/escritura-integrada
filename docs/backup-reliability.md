# Incremento: limites, resíduos, recuperação e Windows

Este documento atualiza os limites de `backups-remotos.md` e `backup-crypto.md`. Não houve conexão de conta, envio cloud, uso de dados reais, publicação ou implantação.

## Tamanho e memória

O envelope cifrado passa de 150 para **512 MiB**, incluindo cabeçalho e tag. SQLite continua limitado a **2 GiB**, verificado antes da cópia e durante o callback de backup para detectar crescimento. A escrita do ZIP interrompe ao atingir o orçamento, remove seu arquivo parcial e respeita cancelamento; não espera preencher o disco para descobrir o excesso. A análise de originais usa `sqlite3.blobopen` em blocos de 1 MiB, com sobreposição para marcadores de segredo na fronteira, sem carregar um BLOB inteiro.

Há checagem conservadora de espaço para snapshot/verificação e para extração isolada. É uma checagem, não reserva de espaço: outros processos ainda podem consumir disco após a consulta. Falhas de I/O continuam fechando a operação sem ativar dados.

Provas locais com dados sintéticos, todas com hash do conteúdo recuperado conferido:

| Conteúdo | SQLite (bytes) | Envelope (bytes) | Geração / recuperação |
|---|---:|---:|---:|
| 8 MiB repetitivos | 13.357.056 | 262.851 | 0,20 s / 0,04 s |
| 8 MiB aleatórios | 13.357.056 | 8.641.473 | 0,32 s / 0,09 s |
| 160 MiB aleatórios | 172.949.504 | 168.234.338 | 6,16 s / 1,12 s |
| 500 MiB aleatórios | 529.928.192 | 525.218.753 | 18,53 s / 3,35 s |

Os valores são observações deste executor, sem rede e sem SLA. Um payload de 512 MiB é recusado antes de cifrar porque o envelope ultrapassaria o máximo. O ensaio sintético de SQLite de 2 GiB está descrito abaixo. Não houve medição de pico de RSS em produção nem homologação de throughput cloud. O KDF opcional scrypt ainda consome aproximadamente 128 MiB além dos buffers.

## Ensaio independente do limite SQLite de 2 GiB (2026-11-16)

`python scripts/backup_2gib_probe.py --work-parent artifacts/backup-2gib` cria exclusivamente bancos sintéticos num diretório temporário novo, sem ler dados operacionais. Exige pelo menos 12 GiB livres antes de começar e usa o disco escolhido, não `/tmp` implicitamente. Neste executor Linux havia 55.314.587.648 bytes livres no workspace e cerca de 6,4 GiB de memória disponível; `/tmp` tinha apenas 3,4 GiB livres e não foi usado para o ensaio grande. A checagem de espaço não é reserva nem garantia contra consumo concorrente.

Resultados registrados em `artifacts/backup-2gib/probe.json` (artefato local ignorado pelo Git):

- SQLite de origem com **2.147.483.648 bytes exatos**, alocado por SQLite com BLOBs sintéticos preenchidos com zeros, sem cabeçalho forjado nem arquivo sparse usado como banco. `integrity_check` aprovado.
- ZIP de 4.998.785 bytes; envelope AES-GCM de 4.998.930 bytes, abaixo dos 536.870.912 bytes permitidos. Geração em 24,299 s e recuperação em 9,546 s nesta execução.
- Banco recuperado com 2.147.479.552 bytes: a sanitização e o `VACUUM` reduziram uma página de 4 KiB. O teste comprova entrada de exatamente 2 GiB e extração próxima desse teto, **não** extração de exatamente 2 GiB nem equivalência binária da origem com o snapshot sanitizado.
- Todos os 2.140.283.904 bytes de payload recuperado foram conferidos por SHA-256 (`02a868ac72f8f332d7126196b00628f58e79d23ba615629594043303b6dc2e41`). O hash do SQLite recuperado corresponde ao manifesto; a origem manteve seu hash após backup/recuperação. Destino existente foi recusado e permaneceu inalterado.
- Após acrescentar uma tabela real, origem de 2.147.487.744 bytes foi recusada com `backup_size`, sem arquivo parcial ou staging residual.
- Caso independente com **520 MiB aleatórios**, SQLite de 550.928.384 bytes: recusado pelo orçamento do pacote com `backup_size`, em 20,203 s, preservando a origem e removendo saída parcial/staging. Portanto, aceitar SQLite de 2 GiB depende também da compressibilidade: não se promete backup de qualquer banco até esse tamanho.
- Diretórios sintéticos foram removidos ao final. Permaneceram somente métricas/logs, sem chaves ou payloads. Remoção lógica, sem promessa de apagamento físico. Os tempos não são SLA; não foram medidos throughput cloud, pressão real de memória nem concorrência de uma carga de produção.

`tests/test_backup_space.py` adiciona seis testes: ENOSPC após escrita parcial de ZIP, envelope e plaintext de descriptografia; ENOSPC na extração com recuperação posterior e recusa de sobrescrita; espaço insuficiente no preflight de restauração; limpeza apenas de área marcada, preservando inclusive diretório com UUID válido mas sem marcador. A falta de espaço é **injetada**: o volume real não foi preenchido e não houve montagem privilegiada. Os testes existentes continuam cobrindo queda abrupta e limpeza sob o bloqueio do worker.

Comandos de reprodução:

```sh
mkdir -p artifacts/backup-2gib
.venv-backup/bin/python scripts/backup_2gib_probe.py --work-parent artifacts/backup-2gib
.venv-backup/bin/python -m unittest tests.test_backups tests.test_backup_crypto tests.test_backup_reliability tests.test_backup_space -v
```

O ensaio grande é opt-in e não roda durante descoberta normal de testes. Este incremento altera somente ensaios, testes e documentação; não altera limites, deploy, permissões dos dados operacionais ou adaptadores cloud.

## Contratos de provedores verificados

- **Dropbox:** até 150 MiB usa `/files/upload`; acima disso, sessão sequencial `start`, `append_v2` e `finish`, em blocos de 8 MiB, offsets explícitos e commit estrito sem renomear/sobrescrever. Confirma `content_hash` e tamanho. Sessões incompletas podem permanecer até expirar; não há repetição automática de uma operação ambígua. [Upload sessions](https://docs.dropboxapi.com/dropbox-api/api-reference/user-endpoints/files/upload-session-start), [finish](https://docs.dropboxapi.com/dropbox-api/api-reference/user-endpoints/files/upload-session-finish).
- **Google Drive:** sessão resumable, blocos de 8 MiB (múltiplo de 256 KiB), `Content-Range`, confirmação intermediária `308` e `Range`, conclusão `200/201` com tamanho/MD5. ACK parcial/ausente ou conexão perdida interrompe com estado incerto; não há retomada automática/persistente neste incremento. A criação declara `supportsAllDrives=true` e `ignoreDefaultVisibility=true`; a pasta ainda precisa conceder acesso e suas permissões continuam herdadas. A URL de sessão permanece restrita ao host oficial antes de receber token. [Contrato de upload](https://developers.google.com/workspace/drive/api/guides/manage-uploads), [files.create](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/create).
- **Amazon S3:** PUT único, SigV4, `If-None-Match: *`, SHA-256 fornecido ao servidor. 512 MiB permanece abaixo do máximo de PUT único; multipart não foi implementado. Se faltar checksum na resposta, faz HEAD assinado com checksum habilitado e verifica tamanho/digest. Além de `PutObject`, essa confirmação requer permissão de leitura do objeto; SSE-KMS pode exigir permissões KMS adicionais. Erro/permissão insuficiente nunca vira sucesso presumido. [PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html), [HeadObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html), [checksums](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html).
- **MinIO/AIStor:** acrescenta `x-amz-checksum-algorithm: SHA256`, conforme a documentação do AIStor. A confirmação por HEAD cobre a ausência do checksum no PUT, pois a documentação descreve retorno na leitura. Compatibilidade de versões antigas/community continua dependente de teste da instalação; resposta sem prova do checksum é recusada. [Compatibilidade S3 e checksums](https://docs.min.io/aistor/developers/s3-api-compatibility/).

Os contratos foram exercitados com transporte simulado, incluindo offsets, corpo parcial, ACK divergente, conclusão, host malicioso e falha de permissão no HEAD. Nenhuma credencial real foi utilizada. Não é homologação de conta/quota/rede. O limite continua comum aos quatro destinos e há apenas um destino configurado por instalação.

## Limpeza lógica e falhas abruptas

Cada execução usa `backup-control/work/<id>/`, marcado por `.backup-work-v1`. ZIP aberto, snapshot, descriptografia e verificação ficam dentro dessa área privada. Em sucesso ou erro normal a área é removida. No próximo tick após queda abrupta, o worker adquire o mesmo bloqueio usado pela recuperação, marca a execução interrompida e limpa somente áreas com identificador e marcador próprios válidos.

Não são removidos `.eibk`, diretórios de restauração, pastas desconhecidas, diretórios antigos sem marcador ou dados operacionais. Links, junctions/reparse points e arquivos especiais provocam recusa e exigem revisão local. Os testes incluem `os._exit` em subprocesso e garantem preservação de arquivos externos. A remoção é lógica: não promete apagamento físico em SSD, snapshots, swap, backups do SO ou memória. Use proteção de disco e controle de acesso.

Temporários criados em versões anteriores diretamente sob `backup-control`, sem marcador de propriedade, continuam exigindo inspeção manual. Também não se apagam resíduos de uma recuperação CLI arbitrária fora da área gerenciada; não se varre a pasta escolhida pelo usuário.

### Recuperação interrompida

Backup e restauração da aplicação são serializados pelo mesmo bloqueio, impedindo que a limpeza remova staging ativo. Chave incorreta/corrupção continua recusada antes de liberar plaintext no destino final. Uma queda durante a extração pode deixar um diretório de restauração parcial ou ainda não validado. Ele **é preservado**, não ativado e não sobrescrito. A repetição no mesmo destino retorna conflito; recupere para uma nova pasta pela CLI e valide. O teste de queda nessa fase comprova limpeza do staging, preservação do destino anterior e recuperação bem-sucedida em outro destino isolado.

## Windows: implementação nativa e limite da validação

Foi adicionada uma camada sem dependência pywin32, usando Win32 via ctypes:

- Diretórios de backup/staging/recuperação são criados com DACL protegida, acesso ao proprietário e SYSTEM, antes da escrita de plaintext. Diretórios existentes recebem a DACL restrita; links/reparse points são recusados.
- O volume deve informar `FILE_PERSISTENT_ACLS`; FAT/exFAT ou falha na configuração privada deixam somente o recurso de backup indisponível. O resto da aplicação continua funcionando, sem fallback para área aberta.
- O arquivo de chave local é protegido por DPAPI no escopo do usuário, com UI proibida; não usa `CRYPTPROTECT_LOCAL_MACHINE`. Falha de DPAPI não aceita chave em claro.
- No Windows, `keygen` exige `--passphrase`: preserve a frase de recuperação offline. O blob DPAPI normalmente depende do usuário/computador original; a frase permite a recuperação do envelope scrypt em outro ambiente com `restore --password`. Não basta copiar o blob DPAPI para outro computador. Chaves aleatórias POSIX existentes não são importadas automaticamente no Windows.
- O bloqueio msvcrt foi corrigido para usar sempre o byte zero, sem aumentar o arquivo a cada aquisição.

Fontes Microsoft: [DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata), [SID de proprietário](https://learn.microsoft.com/en-us/windows/win32/secauthz/sid-strings), [ACL persistente no volume](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationw).

**Este executor é Linux.** Testes de contrato e falhas usam mocks; existe um teste nativo Windows marcado para executar somente nesse sistema. Não foram homologados NTFS/ReFS, serviço com perfil carregado, troca real de usuário, roaming, políticas corporativas ou empacotamento final Windows. Essa validação nativa permanece obrigatória antes de ativar backups Windows em produção. Não foi usado Wine nem contornado EPERM.

## Comandos locais

```sh
python -m unittest tests.test_backups tests.test_backup_crypto tests.test_backup_reliability -v
python scripts/backup_size_probe.py
node --test frontend/tests/*.test.js
npm run build --prefix frontend
python scripts/browser_backups.py
```

A suíte geral existente é executada separadamente; bloqueios EPERM e skips são reportados, sem transformar testes indisponíveis em sucesso.
