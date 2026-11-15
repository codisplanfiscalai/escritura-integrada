# Integrações: diagnóstico e incremento PostgreSQL 1

## Proveniência e recuperação

- Repositório confirmado pelo conector GitHub: `codisplanfiscalai/escritura-integrada`, ID **1448900908**.
- Clone isolado: `/workspace/escritura-integrations-20261114`.
- Remote: `https://github.com/codisplanfiscalai/escritura-integrada.git`.
- Base conferida e reconferida: `develop` **d986105d74ac054fc4cd0e43124d812d8051877b**.
- As PRs 24–27 estão mescladas nessa base. Não foram reaplicadas nem substituídas.
- `feat/integrations-postgres-validation` continua em **13216cfd132e36d6092cfbcc8240d64581c1c6c9**.
- O candidato informado `1c78c76` não foi encontrado pelo endpoint de commits do GitHub (422), no clone completo, nas branches nem após buscar os heads das PRs 1–30. `git fsck --full --no-reflogs` não encontrou objetos recuperáveis.
- Não havia checkout anterior ou bundles informados no ambiente desta tarefa. Não foram acessadas sessões privadas.
- **Perda de fonte registrada:** este incremento foi reconstruído da develop atual. Não equivale ao candidato perdido e não reaproveita/publica `214afe1`.
- Não foram encontrados `AGENTS.md` ou `.agents/skills` aplicáveis no checkout/ancestrais disponíveis.

## Diagnóstico da develop

| Área | Evidência na fonte | Lacuna para o objetivo |
| --- | --- | --- |
| Persistência | `app/db.py`: sqlite3, WAL, PRAGMA, migrações e transação com contexto | Não há backend PostgreSQL do aplicativo. |
| Contrato SQL | `app/core.py` e serviços: `?`, `lastrowid`, `INSERT OR IGNORE`, `COLLATE NOCASE`; catálogos usam JSON SQLite | Portar explicitamente SQL, IDs, ordenação e tipos. Não basta trocar a conexão. |
| Migrações | `app/migration_global_accounts.py` usa `sqlite_master`, reconstrução de tabelas e PRAGMA | Criar schema PostgreSQL nativo completo e caminho de migração de dados verificável. |
| Concorrência | SQLite usa `BEGIN IMMEDIATE`; há geração de IDs por máximo vivo/histórico em `app/core.py` | Definir locks/sequências e preservar IDs históricos; não transportar `MAX(id)+1` sem proteção. |
| Docker | `compose.yaml` e `deploy/*/compose.yaml` oferecem PostgreSQL como perfil opcional; `scripts/run_container.py` chama `create_app`, que instancia SQLite | PostgreSQL obrigatório no Docker **ainda pendente**. SQLite só nos binários offline é requisito de destino. |
| Domínio e segurança | `BusinessCore`, `permissions.require`, políticas HTTP e revalidação de contexto em `Database.transaction` | Reutilizar e adaptar esses controles para API, webhooks e agentes. Esta infraestrutura não autoriza operações de negócio. |
| XML e competência | Importação existente tem prévia/confirmação, original, hashes, empresa e competência | Recepção deve entrar nesse fluxo, preservando o original e as políticas atuais; não escriturar automaticamente por emissão. |
| CNPJ | `normalize_cnpj` já valida CNPJ alfanumérico; há teste existente | Preservar a validação em certificados, credenciais, provedores e recepção, ainda ausentes. |
| A1 / NF-e / NFS-e | Importadores locais e tabelas fiscais; nenhuma recepção A1 encontrada | Faltam cofre/configuração A1, transporte, autorização por empresa, idempotência e recepção/download. |
| Auditor / CT-e / MDF-e | `app/auditor.py` declara ausência de consulta SEFAZ/assinatura e limites CT-e/MDF-e | Leitura e fixtures não constituem integração externa ou homologação real. |
| Backup e manutenção | `app/maintenance.py`, `app/snapshots.py`, desktop dependem de SQLite | Desenhar backup/restauração PostgreSQL e testar recuperação antes da adoção no servidor. |

## Incremento implementado

`app/postgres_backend.py` contém uma infraestrutura nativa e isolada:

- Configuração explícita de host, banco e usuário; rejeita DSN ausente, SQLite, serviço implícito, schema inválido e timeouts inválidos. Não escolhe PostgreSQL/SQLite por tentativa e erro.
- Driver Psycopg 3 e servidor PostgreSQL 17 ou superior; somente **17.11** foi exercitado nesta etapa.
- Uma conexão por operação, parâmetros `%s`, resultados em dicionários e IDs via `RETURNING`. Não há tradução genérica de SQL SQLite.
- Transação com commit único, rollback em exceções inclusive interrupção e fechamento da conexão. O contexto do driver impede `commit()` explícito que quebre a atomicidade.
- Leitura em transação `READ ONLY`; `snapshot=True` usa `REPEATABLE READ`. Timeouts de instrução/lock e timezone UTC são locais à operação.
- Schema precisa existir; não há fallback silencioso para `public` quando o configurado está ausente.
- Migrações nativas sequenciais, checksum SHA-256 e histórico. Uma trava consultiva transacional serializa inclusive a primeira criação do histórico. Fonte antiga, versões ausentes e checksum divergente são recusados. DDL, dados e histórico pendentes sofrem rollback juntos.
- Falha ao conectar gera mensagem sem DSN/credenciais. Erros SQL continuam internos ao chamador; ainda falta o mapeamento seguro para HTTP ao integrar a API.

`requirements-postgres.txt` fixa o driver opcional. O job `postgres-backend` da CI usa servidor real e o comando dedicado falha se não houver driver/DSN, evitando sinalizar sucesso com testes pulados. Na descoberta genérica de testes, a ausência dessa configuração pula apenas o conjunto opcional.

**Este módulo ainda não é utilizado por `create_app`, pelos serviços ou pelo Docker.** Não cria schema de domínio nem substitui `Database`; a aplicação continua usando SQLite. O incremento não pode ser apresentado como conclusão do requisito PostgreSQL obrigatório no Docker.

## Validação local executada

Ambiente: Python 3.12, Psycopg/Psycopg Binary 3.3.9. Dependências de teste instaladas de `requirements-test.txt`; esta execução não usou o lock completo do runtime Docker.

Servidor real em contêiner local descartável, sem volume persistente e com porta em loopback. Imagem já fixada pelo projeto:

`ghcr.io/codisplanfiscalai/escritura-integrada-postgres:17.11-bookworm-479e959b5363ce7a`

Digest obtido: `sha256:ad41f23a1bc852afde5e44171999985862ddcfde6f842ef40bb75888553fdb21`.

O servidor informou PostgreSQL 17.11 (Debian 17.11-1.pgdg12+2), x86_64. Cada teste real criou e removeu seu próprio schema; a consulta final encontrou **zero** schemas `test_backend_%`.

```sh
# Defina ESCRITURA_POSTGRES_TEST_DSN somente para um banco descartável.
# Os testes criam e apagam schemas próprios nesse banco.
PYTHONPATH=. .venv/bin/python tests/test_postgres_backend.py

ESCRITURA_DATA_DIR=/tmp/escritura-pg-rebuild-regression PYTHONPATH=tests:. \
  .venv/bin/python -m unittest test_core test_company_accounting_settings \
  test_plan_manager test_global_account_plans test_importers test_operational_settings -q

.venv/bin/python -m pip check
.venv/bin/python -m compileall -q app/postgres_backend.py tests/test_postgres_backend.py
git diff --check
```

Resultados:

- **19 testes PostgreSQL/configuração passaram**: 16 usam servidor real e 3 validam configuração/fonte (1,018 s na execução final).
- Cobrem commit, rollback após efeito/auditoria sintéticos, interrupção, proibição de commit antecipado, integridade por FK composta, unique/check, snapshot, leitura protegida, indisponibilidade, timeout, migração concorrente, retry após falha, manutenção de dados/histórico anterior e detecção de divergência.
- Um teste armazena e recupera os bytes da fixture `nfe_ficticia.xml` integralmente em `bytea`, um identificador alfanumérico e centavos grandes em `bigint`. Não valida recepção fiscal, certificado, assinatura ou autorização externa.
- **92 testes existentes passaram** (33,022 s), incluindo domínio/API, importadores, parâmetros operacionais, parâmetros contábeis e gerenciador de planos.
- `pip check`, compilação sintática e diff-check passaram.
- Comando dedicado sem DSN foi exercitado: saída 1 com instrução de configuração; não produz falso resultado de homologação.
- A primeira tentativa da regressão parou na importação da API por diretório padrão do perfil sem escrita. Foi corrigida apenas a variável `ESCRITURA_DATA_DIR` para `/tmp`; a execução acima passou. Nenhuma correção funcional foi necessária.

## Limites e próximo incremento

Não houve push, PR, merge, release, implantação, acesso a produção ou alteração de dados reais. CI remota ainda não executada. Não foram executados suíte integral, build da aplicação, navegador, instaladores ou migração completa PostgreSQL. As tabelas `probe_*` são fixtures de infraestrutura; inclusive a tabela de auditoria dos testes é sintética e não é a auditoria do aplicativo.

Próximo incremento: portar o schema e a camada transacional do aplicativo para PostgreSQL nativo, preservando a revalidação de sessão, permissões, contexto da empresa/competência e auditoria dentro da mesma transação. Adaptar primeiro um fluxo de domínio existente, testá-lo nos dois backends e comprovar rollback e concorrência com as mesmas regras. Depois cobrir os demais serviços, os históricos de IDs e backup/restauração; somente então tornar PostgreSQL obrigatório no Docker, atualizar runtime locks e todas as cópias do Compose, e recusar configuração incompleta sem fallback SQLite. Os binários offline continuam com SQLite.

Recepção/download NF-e e NFS-e com A1 entra em incremento posterior: XML integral e hash, deduplicação, identidade alfanumérica da empresa, permissões, auditoria, retries e fluxo existente de prévia/confirmação. Transporte externo, certificado e homologação oficial precisam de evidências próprias e devem ser distinguidos de fixtures. CT-e/MDF-e permanecem explicitamente fora da recepção desta etapa. Não implementar emissão, cancelamento ou manifestação fiscal. Atlas depende dessas bases e não está incluído.

Para coordenação, o commit local deve acompanhar um bundle Git autossuficiente e um patch, com manifesto de hashes e cópia persistente do pacote. A identidade do novo commit e dos artefatos será informada na entrega, sem confundi-la com `1c78c76`.

Referências técnicas consultadas: [transações Psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) e [locks PostgreSQL 17](https://www.postgresql.org/docs/17/explicit-locking.html).
