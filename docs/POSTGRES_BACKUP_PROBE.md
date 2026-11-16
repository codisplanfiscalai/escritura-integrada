# Backup PostgreSQL sintético na fila — sem suporte operacional

## Histórico inicial: inventário e conclusão

A PR52 (0f4218806b2f46b52b79787b3f012c206a18d923) implementa backup operacional **SQLite**, não PostgreSQL. app/db.py fixa escritura.sqlite3; backup_archive.build usa sqlite3.Connection.backup; o ZIP e a recuperação aceitam somente esse SQLite e manifesto. BackupService.run chama esse caminho e confere uma cópia SQLite. Nada disso captura o PostgreSQL do Docker.

postgres_backend.py prepara conexões/transações; postgres_migration_stage.py transporta um checkpoint SQLite para JSONB de ensaio. Os testes PostgreSQL existentes não demonstram pg_dump/pg_restore. O staging pode conter sessões dentro de payloads JSONB, portanto excluir somente tabelas chamadas sessions seria insuficiente. Não se adota esse staging como fonte.

Antes deste incremento foram consultadas branches locais/worktrees, arquivos de backup PostgreSQL no workspace e branches/PRs remotas de backup. Havia somente a branch da PR52; as PRs31/33 tratam de fundação/migração e explicitam backup PostgreSQL pendente. Não se encontrou implementação concorrente nas referências consultadas. Não há AGENTS.md nem .agents/skills no checkout. A PR52 e sua branch permanecem intactas; o incremento está em branch local dependente dela.

## Histórico inicial: componente isolado

É prematuro adicionar um seletor PostgreSQL à UI: ainda não há schema operacional PostgreSQL e contrato de sanitização/reconciliação fiscal. Em vez disso, app/postgres_backup_probe.py fornece um componente experimental **somente para fixtures**, inicialmente sem importação pela aplicação, rotas, agendador ou provedores. A integração incremental atual está descrita ao final:

- Endpoint explícito em 127.0.0.1/::1, banco e usuário com prefixo backup_fixture_; PostgreSQL 17 e clientes 17, sem promessa entre majors. POSIX apenas. O usuário precisa provisionar um cluster inteiramente descartável e uma role restrita com CREATEDB, sem superuser, CREATEROLE, REPLICATION, BYPASSRLS ou memberships.
- Seleção explícita de até 20 tabelas public.backup_probe_*. Sem wildcards, schema arbitrário, stored_files, migration_rows ou tabelas de credenciais/certificados. Esses guards não classificam segredos escondidos no conteúdo; **somente dados sintéticos** são admitidos neste ensaio.
- pg_dump custom sem compressão interna, com tabelas de sessão/contextos/tentativas presentes como definição mas sem dados. São exigidas essas três tabelas. Outros objetos dos quais as tabelas dependem podem faltar e provocar falha: não se afirma backup integral do banco.
- ZIP de dois membros (database.dump e manifest.json), manifesto com backend, formato, versões, escopo, exclusões, tamanho e SHA-256; envelope AES-256-GCM já existente na PR52. O helper authenticated_payload foi extraído para autenticar conteúdo genérico sem enfraquecer a validação SQLite. SQLite mantém seu inventário e destino exclusivo.
- Recuperação autentica a tag, checksum externo, inventário e checksum interno **antes de qualquer comando PostgreSQL**. Exige versões aceitas e role restrita; cria banco aleatório backup_restore_<uuid> a partir de template0. Não aceita nome de destino fornecido, não adota banco existente, não usa pg_restore --clean/--create e não executa DROP.
- pg_restore usa --single-transaction, --exit-on-error, --no-owner e --no-acl. Depois confere sessões vazias. Resultado é restored_probe_only, activated=false e logical_payload_reconciliation=false. O sucesso do comando não prova reconciliação fiscal nem saúde da aplicação.
- Se CREATE DATABASE ou restore falhar/expirar, o nome gerado é reportado como possivelmente existente e fica para inspeção. Não há reenvio nem exclusão automática do banco. Repetir cria outro nome.
- Senha somente em PGPASSFILE externo privado (regular, proprietário atual, 0600 ou mais restrito); não lê/retorna o conteúdo em Python, não usa senha/DSN em argv e não herda PGPASSWORD/PGSERVICE/PGOPTIONS/HOME/LD_PRELOAD. Ambiente dos clientes é montado explicitamente, sem shell. TLS é desativado **somente por se tratar de loopback sintético**; não é configuração para produção.
- Subprocessos têm timeout de 60 segundos por comando, cancelamento, término/reap e streams limitados antes de escrever. Dump máximo 64 MiB; pacote até 64 MiB + 64 KiB; saída de controle/stderr até 1 MiB. Diagnósticos brutos de clientes não são persistidos nem exibidos; stderr até em retorno zero impede sucesso. Não há garantia de prazo global, reserva de disco ou limite do armazenamento ocupado no servidor PostgreSQL.
- Preflight local exige cerca de 208 MiB livres. Staging privado temporário é removido no sucesso/erro normal; não se varrem diretórios desconhecidos. Queda abrupta pode deixar staging privado, para inspeção manual: ainda não há recuperação persistente de jobs PostgreSQL. Exclusão lógica, sem promessa de apagamento físico.

## Contratos oficiais e cautelas

O pg_dump oferece snapshot lógico consistente para dados de um banco ativo; não inclui roles/globais. Seleção -t não inclui automaticamente todas as dependências. A política deste protótipo restringe source/dump/restore à major17, embora o utilitário suporte outras combinações. [pg_dump17](https://www.postgresql.org/docs/17/app-pgdump.html).

pg_restore --single-transaction aplica a restauração numa transação, mas SQL do dump pode executar código escolhido na origem. Autenticidade do envelope não torna SQL hostil seguro: somente fontes sintéticas próprias e cluster descartável confiável, sem superuser. [pg_restore17](https://www.postgresql.org/docs/17/app-pgrestore.html).

O arquivo de senha libpq deve ser privado no POSIX. A role do ensaio não deve ter acesso a bancos reais; o passfile deve conter somente credenciais sintéticas do cluster descartável. [PGPASSFILE](https://www.postgresql.org/docs/17/libpq-pgpass.html).

**Não implementados:** migração app→PostgreSQL, schema fiscal PostgreSQL, backup/restauração da stack Docker inteira, configuração do host, objetos MinIO, roles/globais/tablespaces, large objects, PITR/WAL arquivado, extensões, dependências gerais de schema, reconciliação fiscal, rotação/retomada/agendamento PostgreSQL e fronteira de secrets para um schema operacional futuro. Não instala clientes no runtime/Docker, não acessa socket Docker e não modifica workflows. Não é cobertura PostgreSQL de produção.

## Testes e reprodução

Testes locais de orquestração simulam pg_dump/pg_restore/psql; testes de limite/timeout usam subprocessos Python reais. Não confundem bytes PGDMP sintéticos com dump PostgreSQL válido. Cobrem exclusões, versões, role privilegiada, credencial insegura, checksum/tag, cancelamento, formato SQLite recusado, CREATE falho, restore incerto, sessões não vazias, preservação de diretórios desconhecidos e regressões SQLite/AES-GCM.

    .venv-backup/bin/python -m unittest \
      tests.test_postgres_backup_probe tests.test_postgres_backup_probe_integration \
      tests.test_backup_crypto tests.test_backup_space tests.test_backup_reliability tests.test_backups -v

Na primeira etapa o executor não possuía pg_dump, pg_restore, psql, postgres/initdb ou Docker no PATH nem /usr/lib/postgresql, e o ensaio real não foi executado. Na continuação autorizada, clientes e servidor oficiais foram extraídos para uma pasta isolada; o resultado real está na seção seguinte. Não se acessou daemon/socket remoto nem se tentou contornar EPERM. Há cerca de 44 GiB livres no workspace, mas só 1,3 GiB em /tmp; ensaios nativos devem usar diretório no workspace.

Foi preparado tests/test_postgres_backup_probe_integration.py, opt-in, que cria banco sintético novo, compara SHA-256 do payload/BLOBs, confere constraints e sessões vazias e verifica a origem preservada. Requer PostgreSQL17 descartável já provisionado, role backup_fixture_user restrita com CREATEDB, banco de controle backup_fixture_control pertencente à role, clientes oficiais e passfile sintético privado com acesso aos nomes gerados. Não contém segredo literal real, não provisiona daemon e não imprime senha.

Configuração local necessária (somente nomes, sem valores secretos): ESCRITURA_PG_PROBE_DISPOSABLE=yes, ESCRITURA_PG_PROBE_BINDIR (diretório absoluto dos clientes17), ESCRITURA_PG_PROBE_WORK_PARENT (workspace existente), ESCRITURA_PG_PROBE_PORT e ESCRITURA_PG_PROBE_PASSFILE (caminho absoluto). Executar:

    .venv-backup/bin/python -m tests.test_postgres_backup_probe_integration -v

Sem opt-in, o comando dedicado termina sem alegar execução; na descoberta normal há skip explícito. O harness, após sucesso, remove apenas bancos que ele criou e registrou, sem FORCE; isso é limpeza de fixtures, não comportamento de restauração do componente. Bancos com criação/commit incerto ficam para inspeção. A continuação abaixo comprova um caso real de transação pendente durante a captura. Escala, falta de espaço no servidor e falha de energia continuam sem prova real.

Próximo passo após a prova real abaixo: expandir para dependências de schema, escala e queda; definir schema operacional e política de sanitização antes de projetar integração com a UI/agendador. A PR52 deve continuar draft e este incremento não deve ser publicado sem revisão.

## Resultado histórico da primeira etapa local

- 60 testes executados em 7,854 s: 58 passaram; dois skips explícitos (Windows nativo e PostgreSQL descartável não configurado). Inclui os 17 testes novos de orquestração/subprocessos e as regressões de backup SQLite.
- Roteiro de navegador SQLite aprovado: quatro provedores, agenda, cancelamento da confirmação, execução manual, extração isolada, repetição recusada, mobile e ausência de erros JavaScript. Uploader simulado; nenhum envio externo.
- Sintaxe Python e git diff --check aprovados. Comando nativo sem opt-in retornou código 1 e NOT EXECUTED, sem conectar banco.
- Não executados: pg_dump/pg_restore reais, Docker, servidor PostgreSQL, suíte integral do repositório, carga/concorrência PostgreSQL, builds/CI remotos. Os gates históricos da PR52 não aprovam este novo código.
- Somente alterações locais; sem publicação, mudança de workflows, merge ou implantação.


## Continuação: ciclo real local em PostgreSQL 17.12

A continuação autorizada viabilizou o teste local sem nova PR, sem alterar CI/workflows e sem Docker. Pacotes públicos postgresql-17, postgresql-client-17 e libpq5 versão 17.12-0+deb13u1 foram obtidos no repositório oficial de segurança do Debian 13 e extraídos com dpkg-deb -x para artifacts/postgres-native-tools/root. Não foram executados scripts de instalação nem instalado serviço no sistema. Os SHA-256 foram conferidos contra o índice obtido por HTTPS; não se afirma verificação GPG independente.

- Servidor: 72443dcedfa0bdfa79dafdf414c18498b89929eeee1555e987c87154f3082fea.
- Clientes: 53466b127f3f6e95c7a30352db7fcdd7b83d2143a03efbdcd005032b5047aa83.
- libpq5: b93ae6e06672919c28eb018e7e13af34f1a94fc357f21e28488d339faf53ec98.

Fonte dos pacotes: [Debian Security](https://security.debian.org/debian-security/pool/updates/main/p/postgresql-17/). Os executáveis extraídos funcionaram com as bibliotecas existentes; não foram alterados ou envolvidos por wrappers de execução.

scripts/run_postgres_backup_fixture.py cria um cluster novo privado no workspace usando initdb, senha aleatória em arquivo privado e autenticação SCRAM. O servidor escuta apenas TCP em loopback e porta efêmera; sockets Unix são desativados desde a configuração inicial, em acordo com o Endpoint TCP do ensaio. Não houve EPERM, recusa ou mudança posterior de restrições. O bootstrap administrativo existe somente nesse cluster recém-criado. Os testes usam backup_fixture_user com CREATEDB e sem privilégios elevados, e um passfile privado temporário. Passwords não são enviados em argv nem exibidos.

Comando executado:

    .venv-backup/bin/python scripts/run_postgres_backup_fixture.py \
      --bindir artifacts/postgres-native-tools/root/usr/lib/postgresql/17/bin \
      --work-parent artifacts/postgres-native-tools \
      --report artifacts/postgres-backup-probe/native-run.json

Resultado: PostgreSQL server_version_num=170012; três testes reais passaram em 2,151 s (2,343 s incluindo o subprocesso do teste):

1. Ciclo pg_dump → manifesto/ZIP → AES-GCM → autenticação → banco novo → pg_restore: hashes do payload/BLOBs iguais, constraints ativas, sessões vazias no destino e origem preservada. Payload SHA-256: 52b044f09e5ec6448b0c71ffc5c019bbfe498d369e2c99aa90160645ebbacd2b. Dump de 4.471 bytes e envelope de 5.468 bytes; isto é uma prova pequena, não de capacidade/escala.
2. Uma conexão mantém UPDATE não confirmado, comprovado por estado idle in transaction. A captura acontece com o escritor ainda ativo; depois o escritor confirma a mudança. A recuperação reproduz o snapshot anterior, não a escrita pendente nem o estado posterior da origem.
3. Chave incorreta e corrupção da tag, inclusive com checksum externo recalculado, são recusadas. O número de bancos backup_restore_* permanece zero antes/depois dessas tentativas.

O harness verificou que os bancos criados pelos testes foram removidos, desligou somente seu processo PostgreSQL e removeu o diretório temporário do cluster, credenciais e pacotes de backup. Permaneceram executáveis públicos e relatório de métricas, sem payload/segredos. Evidência sanitizada: docs/evidence/postgres-backup-probe-native.json; resultado local completo em artifacts/postgres-backup-probe/native-run.json.

Isso valida o componente experimental no pequeno conjunto sintético e PostgreSQL 17.12. Não adiciona suporte PostgreSQL operacional ao aplicativo, nem cobertura integral Docker/MinIO/roles/globais/PITR. Não houve alteração da PR52; não se criou nova PR somente para provocar CI.

Após ampliar o ensaio nativo, a regressão local padrão executou 62 testes em 7,993 s: 58 passaram e quatro foram ignorados nessa invocação (Windows nativo e os três testes PostgreSQL sem opt-in). Os três PostgreSQL foram executados e aprovados separadamente pelo harness real descrito acima; não se tratou skip como aprovação. Sintaxe Python e diff-check passaram. O código do componente e o helper criptográfico permanecem idênticos ao commit 14ad4fc; esta continuação adiciona harness, testes e evidências. A PR52 foi reconferida como draft no mesmo head 0f4218806b2f46b52b79787b3f012c206a18d923.


## Integração incremental com a fila da aplicação

A origem agora declara seu backend. Database.backend é sqlite; PostgresDatabase.backend é postgresql, ainda recusado pelo serviço de backup. Não há seleção automática por DSN/variáveis de ambiente ou novo seletor HTTP. O runtime operacional continua SQLite.

BackupService usa adaptadores explícitos para captura, verificação e recuperação. PostgresFixtureSource é uma configuração Python exclusiva de ensaio, validada antes de qualquer conexão. Ela compartilha fila, agendamento, cancelamento, upload e histórico existentes; o controle continua SQLite. Jobs novos fixam identidade da origem e backend; mudança entre admissão e execução é recusada. O histórico SQLite anterior recebe migração aditiva e continua recuperável.

O adaptador PostgreSQL verifica restaurando em banco novo e retém esse banco: seu nome é registrado antes de CREATE no histórico. A recuperação solicitada cria outro banco e grava recibo privado no diretório isolado antes de CREATE. Interrupções preservam o recibo/nome e bloqueiam repetição automática no mesmo destino. Nunca usa DROP/clean/religação de produção. Estes registros não constituem garantia universal contra perda de energia. Bancos de verificação exigem limpeza consciente pelo operador do ambiente descartável; somente o harness de testes remove bancos que criou e encerra seu próprio cluster.

O limite PostgreSQL continua 64 MiB de dump, com metadados/envelope limitados; a prova real usa poucos KiB, não homologa esse teto nem o schema operacional. PostgreSQL 17/POSIX, tabelas sintéticas permitidas, sem objetos MinIO, roles/globais, PITR ou migração do runtime. A UI mostra backend e limites informativos definidos no servidor.

Evidência atual: docs/evidence/postgres-backup-application-native.json comprova quatro testes reais no PostgreSQL 17.12 nativo descartável: fila/verificação/upload simulado/recuperação/recibo e repetição; snapshot com escrita pendente; hashes/constraints/sessões vazias; autenticação recusando chave incorreta e corrupção antes de criar banco. Não foi usado Docker nem conta cloud.


## Composição atual após integração da PR52 (dev.32)

A PR52 foi integrada em 82217bcb57210a8d921ed366afe1f3198e53cc42. Esta composição incorpora develop d8ec384528c0dc39953d72760ee3568a472ed371, sem alterar workflows ou o runtime operacional SQLite. As seções iniciais registram etapas históricas, não o estado atual da fila. PostgreSQL operacional continua recusado; PostgresFixtureSource permanece exclusivo de configuração Python sintética, sem seletor HTTP.

No ambiente atual, pacotes oficiais 17.12 com os SHA-256 documentados acima foram novamente obtidos e extraídos sem instalação de serviço. O harness existente criou um cluster inteiramente novo, executou os quatro testes reais e removeu seus bancos, credenciais e cluster. Evidência desta composição: docs/evidence/postgres-backup-dev32-native.json. Dump de 4471 bytes, envelope de 5468 bytes; isto não é aprovação do teto de 64 MiB nem de schema operacional. TCP loopback é o contrato original do harness; nenhuma restrição de socket foi alterada.

Regressões locais: 51 testes de backup/adaptadores executados (50 passaram, um skip Windows); 17 testes simulados/subprocessos PostgreSQL passaram e quatro nativos foram ignorados na descoberta comum, depois executados e aprovados separadamente pelo harness. Frontend: 192 testes e build aprovados. Navegador local permanece bloqueado pelo EPERM já observado no Chromium deste ambiente; não foi contornado. Gate completo e CI do novo head precisam ser avaliados separadamente: estes resultados focados não representam aprovação de pipeline.

O workflow PostgreSQL preparatório existente não equivale ao ensaio de backup: os quatro testes nativos exigem opt-in explícito e são comprovados aqui pelo harness local. Permanecem os limites de POSIX/major17/tabelas permitidas, ausência de cobertura de stack, MinIO, roles/globais, PITR, schema fiscal e homologação cloud/Windows. Não houve ativação de restauração, migração, merge da PR58 ou implantação.


## Composição após PR61 (dev.33)

Base atual desta rodada: develop 4f53d1a0b52fc7c0edffd744bc259128863259e2, com a otimização do Razão da PR61. Composição automática; todos os 14 arquivos da PR61 e os workflows preservados integralmente. O runtime continua SQLite e PostgreSQL operacional permanece recusado.

O harness PostgreSQL 17.12 repetiu os quatro testes reais em cluster novo descartável, com hashes, snapshot concorrente, autenticação e proteção contra repetição; bancos, credenciais e cluster removidos. Evidência: docs/evidence/postgres-backup-dev33-native.json. Mesmo escopo pequeno sintético; não homologa limites de capacidade nem schema fiscal.

Regressões: 50 testes backup/adaptadores passaram, um skip Windows; 17 PostgreSQL simulados passaram, quatro nativos ignorados na descoberta comum mas aprovados separadamente; oito testes do Razão passaram; 192 testes frontend e build aprovados. Sintaxe, versões e diff-check aprovados. Navegador local permanece bloqueado pelo EPERM conhecido, sem nova tentativa ou contorno. Gate agregado não repetido nesta rodada. O CI anterior de dev.32 passou, mas não aprova o novo head/base: exigir novo CI e conclusão da publicação anterior antes de integrar. Sem merge, deploy, contas cloud ou dados reais.


## Composição após PR62 (dev.34)

Base desta rodada: develop 6b53da59a6a8223f59192b0dadbfe16471e95aac, incluindo as subguias acessíveis Prosoft. Composição automática; os cinco arquivos da PR62, seu roteiro ampliado e os workflows foram preservados integralmente. PostgreSQL permanece experimental: runtime operacional SQLite, nenhum seletor PostgreSQL de produção.

O ciclo nativo PostgreSQL 17.12 passou novamente nos quatro testes em cluster sintético novo, removido ao final; evidência em docs/evidence/postgres-backup-dev34-native.json. Regressões: 50 backup/adaptadores passaram e um skip Windows; 17 PostgreSQL simulados passaram, quatro nativos ignorados na descoberta comum mas aprovados separadamente; 64 Prosoft backend e 193 frontend passaram. Build, sintaxe, versões e diff-check aprovados.

O navegador local continua bloqueado pelo EPERM conhecido, sem nova tentativa ou contorno; a execução do roteiro Prosoft ampliado depende do CI deste head. Gate agregado não repetido nesta rodada. O CI anterior passou, mas não aprova esta composição. Nenhum merge, deploy, banco real ou conta cloud; os limites de tamanho, versões, escopo sintético e ausência de suporte operacional permanecem.
