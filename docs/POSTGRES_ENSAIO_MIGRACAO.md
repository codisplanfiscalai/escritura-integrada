# PostgreSQL: checkpoint e ensaio de transporte, incremento 2

## Estado e dependência

Este incremento prepara a preservação e a conferência dos dados antes da futura migração operacional. **Não conecta o aplicativo ao PostgreSQL, não migra empresas para uso pelo aplicativo e não substitui SQLite no Docker.** Os registros transportados são uma representação tipada em staging, não tabelas de domínio operacionais.

Repositório `codisplanfiscalai/escritura-integrada`, ID 1448900908. A PR 31, head `ac5d4f8d22c25b68620143918804d1eb59668e13`, é a dependência de transações PostgreSQL e passou no run 43652203477. A develop observada está em `5da0393b39007fe992fa21763a9da8244ebb8f77`; a diferença funcional desta para a base da PR 31 é apenas o versionamento. A branch deste incremento parte da PR 31, com PR encadeada à branch `feat/postgres-foundation-validation`, para que a revisão contenha apenas o incremento 2. Depois da integração da PR 31, deve ser retargetada para develop e revalidada.

Nenhum arquivo de Compose, sincronizador ou política de pull da PR 32 foi alterado. Sem Atlas, recepção A1, emissão, cancelamento, manifestação, merge, release ou implantação. Só foram usados bancos fictícios e contêiner local descartável.

## O que funciona

`app/migration_checkpoint.py` oferece operações administrativas explícitas:

- Captura SQLite pela API de backup, em conexão de leitura, incluindo commits ainda no WAL. Nunca copia apenas o arquivo principal nem muda o journal da origem. Só a cópia é consolidada em arquivo autossuficiente. O backup tem prazo limitado.
- Valida integridade e FKs declaradas do snapshot. Exige schema atual 6; não executa migrações ou inicialização de `Database` durante a captura/restauração. Schema diferente requer atualização e conferência separadas antes do ensaio.
- Inventaria todas as tabelas de aplicação, inclusive tabelas adicionais regulares, colunas, FKs declaradas, DDL de tabelas/índices/triggers/views, rowids acessíveis ou PK composta e todos os valores. Tabelas virtuais/shadow e rowids inacessíveis são recusados, sem descarte silencioso.
- Preserva valores com tags de tipo. Inteiros usam strings decimais, REAL usa representação hexadecimal, texto e BLOB usam base64. Isso conserva precisão, XML binário, valores nulos e texto com U+0000, que JSONB não aceita diretamente.
- Calcula hash SHA-256 de cada linha ordenada por rowid/PK e hash por tabela; registra contagem e soma de cada coluna `*_cents`, por empresa ou origem empresarial. Somas usam inteiros Python e strings decimais, sem overflow de SUM int64. Valores monetários não inteiros são recusados. Grupos `global` representam dados globais ou company_id nulo; não atribuem autorização.
- Registra os metadados `sqlite_sequence`, o maior ID vivo e reservas de IDs dos movimentos removidos de `bulk_deleted_movements`. Para PK inteira simples chamada `id`, informa limite inferior do próximo ID e esgotamento int64. PK textual/completamente composta não recebe sequência inventada.
- Faz uma restauração de prova e compara o inventário integral antes de publicar `manifest.json`. Publica apenas em diretório novo; uma falha deixa artefato incompleto, sem manifesto válido. Não substitui nem remove banco/destino preexistente.
- Verifica SHA-256 do arquivo e inventário completo antes de restaurar em outro diretório novo. A restauração não altera configuração nem ativa a cópia.

O snapshot físico conserva também as estruturas internas SQLite. O transporte lógico cobre tabelas de aplicação e metadados de sequência; não porta estruturas internas do otimizador como tabelas de domínio. O artefato é somente do banco: arquivos avulsos, perfil/configuração e caches externos precisam de plano separado. O manifesto não é assinatura digital nem proteção contra um agente que possa substituir simultaneamente banco e manifesto. Checkpoints devem ficar quiescentes e sob controle do administrador.

`app/postgres_migration_stage.py` usa a transação da PR 31:

- Só aceita schema existente com prefixo `migration_`, vazio ou contendo exatamente as duas tabelas do próprio ensaio. Recusa `public`, dados preexistentes e outro checkpoint; nunca mescla nem limpa destino.
- Transfere as linhas para `migration_rows`, conservando nome de tabela, ordinal, localização por empresa, rowid e células tipadas. O manifesto fica em `migration_checkpoint`.
- Relê PostgreSQL em cursor de servidor, recalcula todos os hashes, contagens, totais e localizações por empresa e compara com o checkpoint; revalida a origem do transporte antes do commit.
- A criação das tabelas, todas as linhas e a marca `verified` pertencem à mesma transação. Falha ou interrupção reverte tudo. Não usa sequências de negócio nem `setval`; não há contador operacional a restaurar nesta etapa.
- Retry do mesmo checkpoint revalida todos os dados antes de retornar `duplicate`; divergência é erro e não provoca reparo/sobrescrita. Uma trava consultiva serializa tentativas concorrentes.
- `verify` usa snapshot PostgreSQL REPEATABLE READ/READ ONLY. O resultado sempre declara `verified_staging_only` e `cutover_performed=false`.

As FKs são verificadas no SQLite capturado e seus valores são preservados pelo hash de todas as células. Não se afirma que o staging implementa as constraints de domínio PostgreSQL ou que valida vínculos sem FK declarada, políticas de autorização, saldos contábeis ou regras fiscais. O localizador por empresa permite conferir segregação do transporte; não é autorização multiempresa nem RLS.

## Uso administrativo

Os comandos são ferramentas locais de preparação, não rotas HTTP nem operação normal do aplicativo. Não há seleção automática de banco ou fallback. Use somente cópias autorizadas e schema novo/isolado de teste nesta etapa; não aponte para produção. Dependência: `requirements-postgres.txt` da PR 31.

```sh
python -m app.migration_checkpoint create /copia-autorizada/escritura.sqlite3 /ensaios/checkpoint-novo
python -m app.migration_checkpoint verify /ensaios/checkpoint-novo
python -m app.migration_checkpoint restore /ensaios/checkpoint-novo /ensaios/restauracao-nova

# O DBA prepara previamente um schema novo migration_* em um PostgreSQL de teste.
# Defina ESCRITURA_MIGRATION_DSN explicitamente em ambiente protegido; não na linha de comando/logs.
python -m app.postgres_migration_stage stage /ensaios/checkpoint-novo --schema migration_ensaio
python -m app.postgres_migration_stage verify /ensaios/checkpoint-novo --schema migration_ensaio
```

O checkpoint contém dados completos do banco, inclusive hashes de senha, sessões e auditoria. Arquivos gerados usam permissões restritas; controle também permissões do diretório pai e do PostgreSQL e o transporte TLS quando não local. Não anexar dados reais em PR, relatório público ou logs. O CLI imprime somente estado e identificador do snapshot, não os registros ou o DSN.

## Provas locais executadas

Python 3.12; Psycopg/Psycopg Binary 3.3.9. PostgreSQL real 17.11, imagem fixada pelo projeto `ghcr.io/codisplanfiscalai/escritura-integrada-postgres:17.11-bookworm-479e959b5363ce7a`, em contêiner local com dados em tmpfs, porta loopback, usuário e senha exclusivos de fixtures. Nenhuma instância preexistente foi alterada. Cada teste PostgreSQL cria/remove somente seu próprio schema descartável.

```sh
# ESCRITURA_POSTGRES_TEST_DSN: exclusivamente o banco descartável dos testes.
PYTHONPATH=tests:. python -m unittest test_migration_checkpoint test_postgres_migration_stage test_postgres_backend -v

ESCRITURA_DATA_DIR=/tmp/escritura-migration-regression PYTHONPATH=tests:. \
  python -m unittest test_maintenance test_import_package_cleanup test_core \
  test_company_accounting_settings test_global_account_plans -q
```

- **38 testes passaram em 14,289 s**: 10 novos de checkpoint, 9 novos de staging em PostgreSQL real e 19 da fundação (16 reais e 3 de configuração). São 25 testes usando PostgreSQL real no conjunto.
- **66 regressões existentes passaram em 32,794 s**, cobrindo manutenção/restauração, limpeza autorizada de originais, domínio/API, parâmetros e planos globais.
- As fixtures incluem duas empresas, CNPJ alfanumérico de demonstração, documentos/títulos/journals vinculados, usuários, sessão, grupo/permissões, auditoria, XML original, texto com NUL/Unicode, PK composta WITHOUT ROWID, sequência acima do máximo vivo e tombstone com ID superior.
- O teste WAL mantém aberta a conexão, confirma alteração somente no WAL, inicia outra alteração não confirmada e captura: o commit aparece no snapshot, a alteração não confirmada não aparece e o arquivo principal/journal da origem permanece intacto enquanto a conexão é mantida.
- Restauração de banco inteiro preserva inventário, autenticação e grupo. Reserva AUTOINCREMENT 200 permanece com próximo mínimo 201; movimento removido 900 exige mínimo 901; esgotamento int64 é sinalizado, sem reinício do contador.
- Testes reais confirmam preservação de todas as linhas das tabelas de aplicação, bytes e IDs; totais acima de int64 no manifesto; detecção de alteração do valor/empresa; recusa de schema ocupado/public/outro checkpoint; atomicidade após falha no meio do transporte e na conferência; retry sem duplicação e duas tentativas concorrentes.
- Compilação e diff-check passaram. O job PostgreSQL existente passa a executar também o arquivo de staging com comando que exige driver/DSN; o filtro da CI inclui a branch base da PR 31 para executar durante a revisão encadeada, mantendo permissões somente de leitura. A descoberta genérica executa os testes SQLite e pula somente os PostgreSQL quando o ambiente não os configura.
- Os cinco comandos administrativos create/verify/restore/stage/verify foram executados em processo separado com PostgreSQL real; todos retornaram saída 0 e `cutover_performed=false`. Origem e restauração permaneceram com inventários idênticos. O comando dedicado de staging sem DSN retornou saída 1, sem falso resultado de homologação.

Isso valida o transporte e a preparação em fixtures. Não é homologação fiscal, de uma base real, do runtime PostgreSQL, de escala, de disco cheio/quebra de energia ou de um cutover de produção. Dependências locais seguem requirements de teste, não o lock completo da imagem de aplicativo. CI remota deve ser conferida na PR; não é presumida por estes resultados.

## Condições para a futura migração operacional

1. Portar o schema completo para DDL PostgreSQL explícito, incluindo tipos, índices, constraints, views e equivalentes dos triggers; adaptar SQL/IDs em todos os serviços. Preservar sessão/permissões, revalidação de contexto empresa/competência e auditoria atômica em interface/API/webhooks/agentes. Staging não pode ser conectado ao aplicativo como se fosse esse schema.
2. Bloquear novas escritas de todos os processos e workers antes da captura final e da troca. O snapshot online atual é consistente em um ponto; alterações posteriores da origem não são replicadas. Definir marcador de quiescência e detectar alterações entre captura e ativação; não executar escrita simultânea nos dois bancos.
3. Conservar a origem e o checkpoint completo, testar restauração independente e manter uma cópia protegida fora do host. Inventariar/capturar também arquivos externos e configuração necessários à operação. No PostgreSQL ativo, definir e provar backup/restauração próprios; staging não substitui pg_dump/backup consistente.
4. Importar explicitamente os IDs e vínculos para um destino operacional vazio. Conferir todas as contagens, totais por empresa, hashes de conteúdo/originais/auditoria e FKs; acrescentar verificações semânticas de vínculos não declarados e invariantes do domínio. Nunca mesclar empresas homônimas ou inferir identidade pelo CNPJ sem conservar IDs.
5. Ajustar cada sequência operacional acima do máximo vivo, reservas SQLite e tombstones/históricos pertinentes. Resolver esgotamento antes de ativar. `setval` PostgreSQL não é revertido com rollback transacional: só ajustar no destino ainda não ativo/quiescente e conferir depois; uma falha não autoriza reiniciar sequências existentes. Este incremento apenas produz os limites inferiores, sem ajustar sequências operacionais.
6. Exigir testes do aplicativo completo em PostgreSQL real, inclusive acesso por empresa, simultaneidade, idempotência, fechamento/competência, relatórios, originais, rollback e restauração. Validar em cópias autorizadas das empresas existentes com aceite explícito antes do cutover; fixtures não substituem essa validação.
7. Só trocar a configuração do servidor após todos os gates, com plano de reversão e sem fallback automático para SQLite. Antes de qualquer nova escrita PostgreSQL, o retorno à cópia SQLite verificada é possível sem perder movimentos posteriores porque ainda não existem. **Depois de aceitar escritas no PostgreSQL, voltar ao SQLite antigo perde dados:** é necessário congelar, capturar e reconciliar/reverter todos os novos movimentos por processo próprio validado; não implementar um botão de rollback cego.
8. Após adoção operacional comprovada, tornar PostgreSQL obrigatório no Docker e manter SQLite nos binários offline, preservando as políticas de distribuição em evolução na PR 32. Não promover release estável por este ensaio.

Referências consultadas: [SQLite Online Backup API](https://www.sqlite.org/backup.html) e [isolamento e comportamento não transacional de sequências no PostgreSQL 17](https://www.postgresql.org/docs/17/transaction-iso.html).
