# Dados do Docker junto à stack

Os templates novos usam bind mounts explícitos, sem volumes nomeados novos:

| Serviço | Diretório relativo à stack | Destino no container |
|---|---|---|
| app / SQLite | `./data/<COMPOSE_PROJECT_NAME>/app` | `/data` |
| Redis | `./data/<COMPOSE_PROJECT_NAME>/redis` | `/data` |
| PostgreSQL 17 | `./data/<COMPOSE_PROJECT_NAME>/postgres` | `/var/lib/postgresql/data` |
| MySQL | `./data/<COMPOSE_PROJECT_NAME>/mysql` | `/var/lib/mysql` |
| MinIO | `./data/<COMPOSE_PROJECT_NAME>/minio` | `/data` |

Isso inclui tudo que o aplicativo grava em `/data`, como SQLite, documentos,
relatórios e configurações. A imagem base é somente um insumo de build; não tem
serviço persistente próprio. `/tmp` permanece temporário. Os perfis opcionais
continuam opcionais e não substituem o SQLite do aplicativo.

O caminho é relativo ao diretório do primeiro Compose, não ao diretório interno
do container. Produção e develop têm nomes padrão diferentes. **Mantenha nomes
de projeto distintos e diretórios de stack separados.** Duas stacks configuradas
com o mesmo nome e diretório compartilharão dados; não reutilize uma pasta de
produção para homologação. Preserve o nome atual de uma stack já instalada.

## Stack já usando `./data/app:/data`

Esse bind já mantém os dados junto à stack. **Não execute `init`, `plan` ou
`migrate` para ele e não recopie o volume antigo por cima da pasta atual.** O
volume guardado pode estar desatualizado em relação ao bind que está em uso.
O helper de cópia fria continua limitado aos volumes nomeados e recusa esse
caso sem copiar ou alterar dados; ele não converte binds silenciosamente.

Os templates novos usam `./data/<COMPOSE_PROJECT_NAME>/app` por padrão, um caminho
diferente de `./data/app`. Não substitua o Compose instalado pelo do ZIP para
"atualizar" essa stack: mudar somente o nome do projeto ou o mount não transfere
dados. Mantenha o **Compose atual**, `.env`, projeto, imagens, permissões e mounts
dos demais serviços. A existência de uma pasta vazia no novo caminho não prova
que os dados foram migrados.

Para explicitar a preservação de `./data/app`, o pacote traz o override opcional
`compose.existing-bind.yaml` (no checkout: `deploy/compose.existing-bind.yaml`).
Ele altera somente o mount `/data` do app para `./data/app`, com
`create_host_path: false`. Não copia arquivos, muda permissões, escolhe volumes
de backup, altera imagens/pull policies ou é carregado automaticamente.

1. Faça backup e confira o mount efetivo do app. O `Source` deve ser a pasta
   `data/app` da stack atual, não um volume nomeado nem a pasta de outra stack.
   Confira também o ID da imagem instalada. Use saída filtrada de `docker
   inspect` para mounts/imagem; não divulgue o inspect/config completo com senhas.
2. Conserve o primeiro arquivo abaixo como o **Compose atual da instalação**,
   não o template novo do ZIP. Coloque o override ao lado dele e valide:

   ```sh
   storage_app_container=$(docker compose -f compose.yaml ps --all --quiet app)
   docker inspect --format '{{json .Mounts}}' "$storage_app_container"
   storage_app_image=$(docker inspect --format '{{.Image}}' "$storage_app_container")
   docker compose -f compose.yaml -f compose.existing-bind.yaml config --quiet
   ESCRITURA_IMAGE="$storage_app_image" docker compose -f compose.yaml -f compose.existing-bind.yaml up -d --pull never app
   ```

   Confira que há exatamente um container app e o Source esperado antes do up.
   O exemplo usa a variável `ESCRITURA_IMAGE` dos templates Escritura para fixar
   temporariamente o ID efetivamente instalado, sem regravar o `.env`. Se o seu
   Compose tiver uma referência de imagem personalizada, preserve explicitamente
   esse mesmo ID. Não atualize a tag em paralelo. No Dockge, pode manter o mount já existente
   ou incorporar somente a forma longa desse override no serviço app; não troque
   os mounts dos demais serviços nem o nome da stack. O caminho relativo é
   resolvido junto ao primeiro Compose. O override precisa continuar sendo
   incluído se o arquivo base ainda apontar para outro diretório.
3. Confira novamente `Mounts.Source`, saúde, login, empresas, documentos e
   contagens de controle. Não deve haver nova instalação ou solicitação de criar
   administrador. Preserve a pasta atual e o volume original de backup. Não
   execute limpeza, chmod/chown recursivo ou uma nova cópia durante essa validação.

`./data/app` não inclui o nome do projeto: use diretórios de stack separados
para develop e produção. O override é específico dessa instalação existente;
instalações novas continuam com o isolamento por projeto dos templates padrão.
Se houver outros perfis ativos, mantenha seus mounts reais no Compose atual.
Trocar esses perfis para pastas novas exige um plano próprio, não esta operação
do app. Uma futura cópia do bind para outro diretório também requer uma
manutenção explícita e verificada; esta rota mantém o caminho já utilizado.

## Preparar uma instalação nova

Requer Python 3.10+ no host e Docker local com containers Linux. No repositório,
a ferramenta está em `scripts/deploy_storage.py`; nos ZIPs, `deploy_storage.py`
fica ao lado do Compose. Os exemplos abaixo usam o ZIP e uma stack develop.
Para produção, use o nome exato de seu `.env` e a imagem versionada escolhida.

```sh
docker compose pull app
python3 deploy_storage.py init --project escritura-develop --helper-image ghcr.io/codisplanfiscalai/escritura-integrada:develop
docker compose up -d
```

`init` recusa um projeto que já tenha containers/volumes Compose ou um destino
existente, inclusive vazio. Ele prepara os cinco subdiretórios em staging e os
publica juntos, sem substituição. Não requer ativar os perfis ou preencher seus
segredos. O app/MinIO recebem UID/GID `10001:10001`; diretórios novos têm modo
`0700`. Os entrypoints oficiais Redis/PostgreSQL/MySQL ajustam seus próprios
diretórios ao iniciar. Não use `chmod 777`, não rode o app como root e não altere
recursivamente a propriedade de pastas com dados existentes.

`bind.create_host_path: false` faz o Compose recusar diretórios ausentes. Não há
criação automática de pastas vazias nem fallback para outro banco. Se houver erro
de acesso, confira UID/GID, filesystem e configuração do Docker antes de subir.
No Dockge, a raiz da stack precisa estar no host Docker no mesmo caminho que o
daemon monta; não prepare pastas somente dentro do container do painel. Em hosts
SELinux, configure o contexto autorizado das pastas com o administrador; o
template não relabela automaticamente dados privados.

Os testes reais deste fluxo usam Docker Linux local. Docker Desktop deve permitir
compartilhar a pasta e preservar a semântica de permissões/arquivos usada pelos
bancos; a ferramenta recusa divergências de metadados durante a migração.
Filesystem POSIX local é o destino recomendado para Dockge. Daemons remotos e
drivers de volume externos/NFS não são suportados pela ferramenta.

### Offline

Carregue o tar verificado antes de `init`, passe a **tag versionada local** do app
em `--helper-image` e use os dois arquivos:

```sh
docker load -i EscrituraIntegrada-<versão>-linux-amd64-images.tar.gz
python3 deploy_storage.py init --project escritura-develop --helper-image ghcr.io/codisplanfiscalai/escritura-integrada:<versão>
docker compose -f compose.yaml -f compose.release.yaml up -d --pull never
```

A ferramenta resolve a imagem local para seu ID e sempre usa `--pull never` e
`--network none`. Não baixa utilitários. O override fixa somente imagens/políticas,
preservando os mesmos binds. Binários desktop/offline continuam com seu próprio
armazenamento e não usam esta ferramenta.

## Migrar uma stack existente com volumes nomeados

**Só trocar os mounts por pastas vazias NÃO transfere dados.** O aplicativo pode
parecer uma instalação nova, enquanto os dados continuam no volume antigo.
Não aplique o Compose novo nem execute `init` nessa stack antes deste procedimento.
Ele é uma cópia fria de arquivos, não uma migração de SQLite para PostgreSQL.

1. Faça backup consistente e teste sua restauração. Reserve espaço para outra
   cópia completa e seus backups. Registre nome do projeto, versões/IDs das
   imagens, empresas e contagens de controle. Durante esta operação mantenha as
   **mesmas imagens e versões dos bancos**; faça upgrades em outra manutenção.
2. Antes de editar os mounts, guarde uma cópia do Compose com volumes nomeados
   como `compose.named.yaml`, **no mesmo diretório**, sem sobrescrever backup
   anterior. Preserve o `.env` privado, permissões e `COMPOSE_PROJECT_NAME`.
   Não extraia um ZIP sobre o `.env` atual. A cópia deve representar a configuração
   real; volumes externos, links/tablespaces e montagens personalizadas exigem
   um plano próprio, não uma adaptação improvisada deste comando.
3. Gere um plano novo e confira os nomes dos volumes e o projeto. O arquivo de
   saída e o override `storage-plan.images.yaml` são criados exclusivamente e não
   podem já existir. Mantenha os containers originais, mesmo parados: a ferramenta
   confere seus mounts e IDs de imagens; use `stop`, não `down`:

   ```sh
   python3 deploy_storage.py plan --project escritura-develop --compose-file compose.named.yaml --helper-image ghcr.io/codisplanfiscalai/escritura-integrada:<versão-local> --output storage-plan.json
   ```

   O plano não copia dados e não inclui senhas ou a configuração completa. Ele
   resolve os nomes reais pelo Compose e confere os labels de propriedade dos
   volumes. O volume do app deve existir; perfis nunca usados, sem volume,
   receberão pastas novas. Não adivinha nomes por prefixo nem aceita volumes de
   outra stack. O override fixa os **IDs locais efetivamente instalados**, com
   pull `never`, para um alias develop/latest não provocar upgrade durante a
   mudança de armazenamento. Preserve essas imagens locais; não execute prune.
   Confira o plano e o override antes de continuar.
4. Coloque a stack em manutenção, pare todos os serviços/escritores e impeça
   reinícios pelo painel, automações, jobs de backup ou outros operadores:

   ```sh
   docker compose -f compose.named.yaml --profile '*' stop
   python3 deploy_storage.py migrate --plan storage-plan.json
   python3 deploy_storage.py verify --plan storage-plan.json
   ```

   A ferramenta não para serviços automaticamente. Recusa containers ativos,
   volumes que mudaram de identidade, destinos existentes (mesmo vazios), links
   de dados externos e arquivos especiais. A única exceção é o link de socket
   runtime mysql.sock da imagem oficial: ele é copiado como link, sem seguir
   nem copiar seu destino; tablespaces externos continuam recusados. Usa os volumes originais **somente leitura**
   e sem copy-up. Confere SHA-256 de todos os arquivos, tamanhos, hard links,
   modos, UID/GID e mtime, sincroniza arquivos/diretórios em disco, relê as origens, revalida escritores/identidades e
   publica o conjunto por rename exclusivo no mesmo filesystem. A verificação
   comprova cópia de arquivos/metadados, não homologação funcional dos bancos.
   Escritores devem permanecer parados; as checagens não são uma trava global
   contra um operador iniciar containers simultaneamente.
5. Somente após `migrate` e `verify` aprovados, incorpore os mounts do Compose
   novo. Preserve projeto, portas, credenciais e demais ajustes locais. Confira e
   suba com os IDs congelados, mantendo o override **por último**:

   ```sh
   docker compose -f compose.yaml -f storage-plan.images.yaml config --quiet
   docker compose -f compose.yaml -f storage-plan.images.yaml --profile '*' up -d --pull never
   ```

   Ative somente os perfis que já usava; substitua `--profile '*'` pela lista
   correspondente. Se também usar `compose.release.yaml`, coloque-o antes do
   override de IDs, nunca depois. No Dockge, mantenha a stack em manutenção e
   faça esse primeiro corte pelo CLI com os dois arquivos, ou incorpore
   temporariamente os mesmos IDs/pull `never` nos serviços do Compose do painel.
   Não execute um deploy pelo painel que descarte esse congelamento. Não crie
   outra stack ou troque o nome do projeto para isso.
6. Confira saúde, login, empresas, documentos, contagens/saldos de controle e os
   dados dos perfis ativados **antes de liberar gravações**. O manifesto privado
   fica em `./data/<projeto>/.storage-manifest.json`. `verify` deve ser executado
   antes da subida: os bancos alteram arquivos normalmente ao iniciar, portanto
   uma divergência posterior não deve ser "corrigida" copiando dados por cima.
7. Guarde os volumes originais, Compose antigo e backups até concluir a retenção
   definida pelo escritório. A ferramenta nunca remove, renomeia ou escreve nos
   volumes originais, nunca troca mounts e nunca executa limpeza de volumes.

Depois de homologar o armazenamento, planeje a atualização de imagem em uma
manutenção separada. Usar somente `compose.yaml` retoma as referências do `.env`
e `pull_policy: always` do app da PR 32. O override de IDs não é carregado
automaticamente e não modifica o `compose.release.yaml` do pacote offline.

### Falha, repetição e retorno ao armazenamento anterior

Uma falha na cópia/validação impede publicar o destino e remove somente o staging
privado dessa tentativa. Nenhum destino existente é mesclado ou reparado.
Depois de sucesso, repetir `migrate` recusa o destino; use `verify`, não apague a
pasta para forçar uma repetição. Se a comunicação com Docker for interrompida,
o resultado pode ser incerto: confira o destino/manifesto e o estado dos serviços
antes de qualquer nova ação. Um `.staging-*` retido não deve ser usado como mount.
Não remova pastas ou volumes para resolver uma falha sem verificar seu conteúdo.

Antes de aceitar novas gravações, é possível parar a stack, restaurar o Compose
antigo com os mesmos nomes/versões e subir os volumes originais. Mantenha as pastas
copiadas preservadas para diagnóstico. **Depois de novas gravações no bind,
voltar aos volumes antigos perde essas novas alterações:** congele as escritas,
faça backup dos dois lados e reconcilie/planeje uma cópia reversa separada e
verificada. Não há rollback automático de dados, nem rollback de schema ao trocar
uma imagem. Nunca use `down -v` ou `volume prune` neste procedimento.

O código deste PR e novos ZIPs não migram instalações existentes por conta própria.
Nenhuma migração é executada no servidor do usuário durante o desenvolvimento.
