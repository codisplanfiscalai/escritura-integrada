# PostgreSQL operacional — validação em PR draft

Esta implementação usa tabelas relacionais PostgreSQL reais para autenticação,
escrituração, relatórios, originais, eventos e dados do cofre. Não usa staging JSONB
como banco do aplicativo. Não foi executada migração de cliente nem implantação.
A homologação desta branch não autoriza produção.

## Contrato de execução

O Compose padrão exige PostgreSQL 17+, senha no `.env` e banco saudável. Somente a
porta da aplicação é publicada. Não há fallback SQLite se a conexão, schema ou
histórico falhar. Desktop mantém SQLite por padrão; `ESCRITURA_DATABASE_BACKEND`
aceita apenas `sqlite` ou `postgresql`. A URL isolada não seleciona backend.

O operador precisa apenas de `compose.yaml`, `.env` e armazenamento persistente.
Os comandos abaixo já estão dentro da imagem, sem script externo ou arquivo SQL
no host. Use uma imagem construída desta branch para os testes; imagens antigas
não contêm estes comandos. O `.env` exige `ESCRITURA_IMAGE`, `POSTGRES_PASSWORD`
(senha longa, mínimo 16 caracteres na imagem PostgreSQL do projeto), e pode
configurar `POSTGRES_USER`, `POSTGRES_DB`, `ESCRITURA_DATABASE_SCHEMA`.

Mantenha o mesmo `COMPOSE_PROJECT_NAME` e `ESCRITURA_APP_DATA_BIND` de instalações
existentes. O bind existente não deve ser trocado pelo volume vazio. Quando não
informados, instalações novas usam os volumes `app_data` e `postgres_data`.
`ESCRITURA_POSTGRES_DATA_BIND` permite um diretório PostgreSQL persistente explícito.
Diretórios bind devem existir com permissões corretas para a imagem; não use um
diretório de outro banco. Nunca execute `down -v` para atualizar.

## Instalação nova, sem SQLite anterior

```sh
docker compose up -d postgres
docker compose run --rm --no-deps app python -m app.postgres_transfer initialize
docker compose up -d app
```

A inicialização é explícita, cria o schema operacional somente num schema vazio,
e recusa o caminho de instalação nova se houver `/data/escritura.sqlite3`.
Reinícios validam o histórico/checksum; não recriam nem esvaziam tabelas.
Nenhuma sessão ou empresa de demonstração é criada por padrão.

## Migração explícita de SQLite

Faça primeiro uma cópia de segurança independente do diretório e do COFRE A1.
Pare todos os processos que escrevem nesse SQLite, inclusive desktop, automações
e contêineres antigos. O aplicativo não consegue provar que um processo externo
foi parado; a confirmação abaixo declara essa condição necessária. Escritas
SQLite posteriores ao snapshot não serão transferidas.

```sh
docker compose stop app
docker compose up -d postgres
docker compose run --rm --no-deps app python -m app.postgres_transfer migrate-sqlite --source /data/escritura.sqlite3 --acknowledge-stopped-sqlite
docker compose up -d app
```

O PostgreSQL de destino deve estar vazio: não execute `initialize` antes de
`migrate-sqlite`. Uma segunda importação é recusada, mesmo se aparentemente igual.
O comando usa a API de backup SQLite, incluindo commits no WAL, e atualiza apenas
uma cópia temporária quando necessário. Não reescreve, apaga ou muda journal mode
na origem. Todas as tabelas/colunas conhecidas são transferidas com parâmetros,
IDs, relações, centavos inteiros, blobs, eventos, tombstones e reservas de IDs.
Contagens e hashes de todas as linhas são reconciliados antes do commit.
Gatilhos de integração não reemitem eventos históricos durante a cópia.
DDL, importação, restrições e reinício de sequências são transacionais: falha
impede o commit. Não há mescla nem recuperação automática de uma tentativa incerta;
confira o histórico do destino antes de qualquer nova tentativa.

Preserve a cópia SQLite. Depois de novas gravações PostgreSQL, voltar a ela perde
essas gravações: não existe rollback automático seguro. Uma reversão exige um
plano explícito de reconciliação e parada de escritores.

## Backup e restauração de prova

O painel de backups seleciona o adaptador PostgreSQL operacional e mantém o
encapsulamento AES-GCM e as chaves externas existentes. A verificação restaura
em um schema aleatório, reconcilia todas as linhas e remove somente esse schema
de prova. A restauração manual do painel deixa um schema novo e recibo local;
nunca ativa nem sobrescreve o schema operacional.

Para uma exportação administrativa local (ZIP **não cifrado**, arquivo privado):

```sh
docker compose exec app python -m app.postgres_transfer backup --output /data/backup-pg.zip
docker compose exec app python -m app.postgres_transfer restore --source /data/backup-pg.zip
```

O destino do arquivo deve ser novo. O backup usa snapshot REPEATABLE READ e trava
os escritores do aplicativo durante a captura, inclui originais e reservas de
sequências, e limita o conteúdo lógico a 512 MiB. Para bancos maiores, esta versão
recusa a operação; não trunca. Não altere o banco por ferramentas externas durante
migração/backup. A restauração é atômica em `restore_<identificador aleatório>`;
o papel de banco precisa de permissão CREATE SCHEMA. O resultado informa o schema.
Sessões são invalidadas após a conferência integral. A ativação exige parada,
revisão do recibo, escolha explícita de `ESCRITURA_DATABASE_SCHEMA` e reinício.
Não restaure um ZIP SQLite como backup PostgreSQL; use a migração explícita.

COFRE A1: o ciphertext por empresa em `operations` é preservado; a chave continua
fora do banco, no mesmo volume privado `reception_vault`. Copie/recupere essa chave
separadamente conforme COFRE_A1.md. Sem a chave original, o backup do banco não
recupera o A1. Não exporte certificados, chaves ou dados reais para Git/CI.

## Retorno a SQLite depois do corte: bloqueio técnico

Não há conversor PostgreSQL → SQLite nesta versão. O SQLite preservado contém
somente o estado anterior ao corte. Um lançamento novo, uma alteração ou exclusão
no PostgreSQL não aparece nele. Trocar a variável de backend, copiar esse arquivo
ou importar um CSV financeiro não reconcilia o banco inteiro.

O marcador `_escritura_import` identifica a importação; não é um log reversível.
Os eventos de integração também não constituem CDC completo de todas as tabelas.
Uma reconciliação teria de construir **outro SQLite**, com versão de schema
compatível, e preservar todas as tabelas, tipos, blobs, IDs, relações, tombstones,
reservas em `sqlite_sequence`, auditoria e chave externa do cofre; depois comparar
contagens, hashes e saldos por empresa, invalidar sessões e testar os relatórios.
Esse conversor e essa homologação **não estão implementados**. Portanto, retorno
para SQLite após gravações PostgreSQL está bloqueado, sem promessa de rollback.

A recuperação disponível preserva as novas gravações **continuando em PostgreSQL**:
parar todos os escritores, capturar o banco atual, restaurar em destino novo e
conferir antes de decidir qualquer ativação. O ensaio sintético
`scripts/probes/postgres_recovery.py` migra uma origem SQLite, grava um lançamento
de R$ 123,45 somente no PostgreSQL e demonstra que a origem não o contém; o dump
nativo restaurado preserva esse lançamento e os demais dados. Não executa retorno
para SQLite nem ativa o destino.

## Bases maiores que 512 MiB: recuperação nativa PostgreSQL

O teto do adaptador da aplicação mede os **JSONL tipados descompactados**, não o
arquivo ZIP nem `pg_database_size`. Blobs são codificados em base64: podem consumir
aproximadamente 4/3 do tamanho original, além de metadados. Assim, um banco menor
que 512 MiB pode exceder o teto. A captura recusa o excesso; um arquivo parcial sem
manifesto não é backup válido e a restauração o rejeita. Não aumente apenas a
constante: limites de envelope cifrado, memória, disco, tempo e restauração também
precisariam de homologação. A interface de backups mantém esse limite.

Alternativa administrativa: os utilitários `pg_dump` e `pg_restore` já estão na
imagem PostgreSQL. O formato custom não herda o teto de 512 MiB do aplicativo.
O procedimento abaixo usa somente Compose, o armazenamento e ferramentas presentes
na imagem. Pare também escritores externos e outras instâncias da aplicação;
a parada mantém as reservas de sequências alinhadas ao snapshot. Execute em shell
com erro fatal, confira o espaço disponível e não use `--clean` ou `--create`.

Captura (o nome novo e `noclobber` evitam substituir arquivo existente):

```sh
(
  set -eu
  umask 077
  mkdir -p ./backups
  backup="./backups/postgres-$(date -u +%Y%m%dT%H%M%SZ)-$$.dump"
  set -C
  docker compose stop app
  docker compose exec -T postgres sh -ceu 'exec pg_dump --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' > "$backup"
  sha256sum "$backup" > "$backup.sha256"
  printf 'Dump concluído: %s\n' "$backup"
)
```

Somente considere a captura completa se o comando terminar com sucesso e o hash
for produzido. Falha deixa o app parado e pode deixar arquivo parcial; confira
antes de repetir com nome novo. A retomada do app original é uma decisão explícita.
O arquivo custom é **comprimido, não cifrado**; 0600 não substitui criptografia.
Para uso operacional, guarde-o em armazenamento cifrado com cópia independente;
a UI não oferece cifragem/restauração desse formato. Chave A1 e outros arquivos
externos exigem sua cópia separada.

Restauração de prova (substitua somente o caminho do backup):

```sh
(
  set -eu
  backup='./backups/ARQUIVO-CONFERIDO.dump'
  sha256sum -c "$backup.sha256"
  destino="restore_test_$(date -u +%Y%m%d%H%M%S)_$$"
  docker compose exec -T postgres sh -ceu 'exec createdb --username="$POSTGRES_USER" --template=template0 "$1"' sh "$destino"
  docker compose exec -T postgres sh -ceu 'exec pg_restore --username="$POSTGRES_USER" --dbname="$1" --single-transaction --exit-on-error --no-owner' sh "$destino" < "$backup"
  printf 'Banco novo, não ativado: %s\n' "$destino"
)
```

Se `createdb` falhar, pare: não adote banco existente. Falha de restauração reverte
a transação; o banco novo vazio permanece para diagnóstico. Não altere
`POSTGRES_DB` para esse banco antes da conferência. Diferentemente do adaptador da
aplicação, a restauração nativa conserva sessões: devem ser invalidadas no destino
antes de uma ativação futura. Papéis/tablespaces globais não fazem parte desse dump;
as permissões e dependências exigem conferência em outro cluster. Use ferramentas
da mesma versão principal do servidor. O papel precisa poder criar banco; se não
puder, a criação exige o administrador, sem ampliar permissões automaticamente.

O ensaio obrigatório na CI usa 513 MiB reais de blobs sintéticos compressíveis:
confirma a recusa do adaptador limitado, executa dump/restore nativos e reconcilia
as 86 tabelas (blobs por SHA-256), valores financeiros, empresas, sequências e
marcador de importação. Isso valida correção funcional, **não** prazo de recuperação,
compressão de dados reais ou desempenho em bancos muito maiores. Backup físico
com WAL/PITR é outra opção de infraestrutura; não foi implementado nem homologado
por esta PR. O dump local no mesmo host, sozinho, não cobre perda desse host.

Referências oficiais: [pg_dump 17](https://www.postgresql.org/docs/17/app-pgdump.html)
e [pg_restore 17](https://www.postgresql.org/docs/17/app-pgrestore.html).

## Desenvolvimento e evidência

`app/data/postgres/001.sql` e `002_triggers.sql` são SQL nativo versionado. O
manifesto `source.json` contém a estrutura e os catálogos públicos de referência,
nunca dados de clientes. Novas alterações após publicação exigem nova migração;
não edite um checksum já aplicado. A camada de conexão só reconhece placeholders
fora de literais e comentários, não traduz dialetos por substituição de texto.
Consultas específicas possuem alternativas explícitas, com parâmetros separados.

Os escritores usam trava transacional para manter o contrato anterior de
numeração, idempotência e revalidação do contexto da sessão. Isso prioriza
compatibilidade; não promete escalabilidade de múltiplos escritores simultâneos.
O diretório `backup-control` ainda usa SQLite somente para a fila local de backups,
nunca como fallback ou banco fiscal/contábil.

A CI executa `tests/test_postgres_operational.py` com servidor real e schemas
sintéticos descartáveis, além dos ensaios preparatórios e da suíte agregada.
Consulte os resultados do SHA da PR: ausência de resultado, falha ou skip não é
homologação. Sem merge, deploy ou migração de dados reais nesta tarefa.
