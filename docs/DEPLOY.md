> Nesta branch, o Compose usa PostgreSQL operacional obrigatório. O LEIA-ME.txt do pacote contém o fluxo atualizado, sem scripts externos. Os procedimentos SQLite e de perfis opcionais abaixo são históricos e não devem ser usados para o cutover PostgreSQL.

# Docker, GHCR e implantação

## O que esta distribuição executa

O aplicativo é uma única imagem: API Python, interface Vue compilada e SQLite persistente. O navegador acessa a mesma porta da API e dos arquivos da interface. A base Python e os serviços adicionais têm imagens próprias no namespace `ghcr.io/codisplanfiscalai`, vinculadas a este repositório pelos metadados OCI.

| Imagem | Conteúdo | Uso nesta versão |
|---|---|---|
| `escritura-integrada` | Aplicação + interface compilada | Obrigatório |
| `escritura-integrada-base` | Python + dependências runtime travadas | Base incorporada à aplicação; incluída no bundle offline |
| `escritura-integrada-redis` | Redis upstream + validação de credenciais | Perfil `redis`, opcional e interno |
| `escritura-integrada-postgres` | PostgreSQL upstream + validação de credenciais | Perfil `postgres`, opcional e interno |
| `escritura-integrada-mysql` | MySQL upstream + validação de credenciais | Perfil `mysql`, opcional e interno |
| `escritura-integrada-minio` | MinIO compilado do fonte oficial fixado | Perfil `minio`, opcional e interno |

**Redis, PostgreSQL, MySQL e MinIO ainda não são consumidos pelo backend.** Ativar um perfil não migra dados, não troca SQLite e não cria armazenamento de anexos ou filas no aplicativo. Essas integrações exigem desenvolvimento, migração e validação próprios. O runtime atual usa um processo/worker Uvicorn e um diretório SQLite por ambiente; não escale réplicas nem compartilhe o mesmo arquivo SQLite entre hosts.

As imagens e o bundle desta entrega são `linux/amd64`. Windows usa Docker Desktop com containers Linux quando a opção escolhida for Docker; o aplicativo gráfico Windows tem distribuição separada. ARM64 não é anunciado como validado.

## Instalar a partir da release

Baixe `EscrituraIntegrada-<versão>-production-deploy.zip` ou `EscrituraIntegrada-<versão>-develop-deploy.zip`. Cada pacote contém `compose.yaml`, `.env` preenchido com imagens publicadas, manifesto de imagens e instruções. Não contém código da aplicação, banco, senha de administrador nem material recuperado dos sistemas de referência.

**Stack existente com volumes nomeados:** siga primeiro [STORAGE.md](DOCKER_STORAGE.md). Trocar o mount por uma pasta vazia não copia os dados e pode apresentar uma instalação nova.

**Stack já usando `./data/app:/data`:** mantenha esse mount e seu Compose atual; não execute `init` nem recopie o volume guardado. O caminho padrão novo inclui o nome do projeto e é diferente. A [rota de bind existente](DOCKER_STORAGE.md#stack-já-usando-dataappdata) usa ESCRITURA_APP_DATA_BIND no .env e o mount no próprio compose.yaml para preservar a pasta, sem mover dados ou mudar outros serviços.

Antes de atualizar execute `python3 deploy_storage.py prepare-app --project <projeto-atual> --helper-image <imagem-local-do-app>` no host. O helper seleciona automaticamente o único bind existente plano ou por projeto e grava a escolha no `.env`, preservando credenciais. Override explícito válido tem prioridade. Dois diretórios, banco ausente ou permissões incompatíveis bloqueiam sem copiar/criar dados; o acesso é testado com o USER real da imagem instalada. Campo vazio agora bloqueia o Compose/Dockge: apenas copiar arquivos/clicar em implantar não executa a preparação no host. Leia [o fluxo e seus limites](DOCKER_STORAGE.md#resolver-o-bind-antes-de-atualizar). Depois de subir, `deploy_storage.py check-app --compose-file compose.yaml --project <projeto> --require-health --wait-health-seconds 120` verifica health/API; confira também os dados na interface.

Instalação nova, dentro do diretório extraído (Python 3.10+ e Docker local): baixe/carregue a imagem do app e execute `python3 deploy_storage.py init --project <nome-exato-do-.env> --helper-image <imagem-local-do-app>`. No checkout, use `python3 scripts/deploy_storage.py`. A ferramenta prepara diretórios com permissões próprias e recusa destinos existentes. Depois:

```sh
docker compose up -d
docker compose ps
```

Abra `http://127.0.0.1:8000` em produção ou `http://127.0.0.1:8001` em desenvolvimento. O primeiro acesso cria o administrador. Os arquivos `compose.yaml` estão serializados como JSON, que é uma sintaxe válida para YAML/Compose e permite validação estática sem dependências adicionais.

| Configuração | Produção | Desenvolvimento |
|---|---|---|
| Projeto Compose padrão | `escritura-production` | `escritura-develop` |
| Porta padrão no host | `8000` | `8001` |
| Bind padrão | `127.0.0.1` | `127.0.0.1` |
| Diretório SQLite padrão | `./data/escritura-production/app` | `./data/escritura-develop/app` |
| Estado inicial | Vazio; administrador criado pelo operador | Vazio; administrador criado pelo operador |

Só o serviço `app` declara uma porta publicada no host. Bancos, Redis, S3 e console MinIO permanecem na rede interna, mesmo quando os perfis estão ativos. Os arquivos não têm `build`, bind mount de fontes, `network_mode: host` ou bancos expostos. Cada serviço persistente usa um bind em `./data/<COMPOSE_PROJECT_NAME>/<serviço>`, com `create_host_path: false`. Não há volumes nomeados novos. Veja [preparação, permissões e migração](DOCKER_STORAGE.md).

No `.env`, ajuste `ESCRITURA_PORT` quando necessário. `ESCRITURA_BIND` controla a interface publicada; o padrão loopback restringe o acesso à máquina. Para acesso por rede, planeje o endpoint HTTP/HTTPS e as permissões do host antes de alterar o bind. `ESCRITURA_COOKIE_SECURE=1` destina-se a um endpoint HTTPS já configurado; marcá-lo em HTTP impede o navegador de enviar o cookie de sessão. Os arquivos entregues não instalam proxy TLS, certificados ou serviço Windows.

O Compose da raiz equivale ao de produção e exige `ESCRITURA_IMAGE`. Para partir do repositório, copie `deploy/production/.env.example` para `.env` e substitua a tag indicada por uma release publicada. O exemplo develop acompanha `:develop`, que precisa ter sido promovido no GHCR. O pacote de produção continua fixado à versão publicada por padrão. Para acompanhar a main estável, configure `ESCRITURA_IMAGE=ghcr.io/codisplanfiscalai/escritura-integrada:latest`. `latest` e `develop` são tags mutáveis; baixar uma delas não promove nem altera o canal no GHCR.

### Cartão da aplicação no Dockge

Os templates usam a forma curta de `ports`, como texto. O parser do cartão do [Dockge 1.4.2](https://github.com/louislam/dockge/blob/1.4.2/common/util-common.ts) espera esse formato. A forma longa, com `target`, `published`, `host_ip` e `protocol`, é válida no Compose, mas pode causar `input.split is not a function` no navegador e impedir a exibição do cartão `app`, mesmo com o container iniciado.

Para corrigir um Compose antigo de desenvolvimento, substitua somente a entrada de porta por:

```yaml
ports:
  - "${ESCRITURA_BIND:-127.0.0.1}:${ESCRITURA_PORT:-8001}:8000/tcp"
```

Em produção e no Compose da raiz, o padrão de `ESCRITURA_PORT` é `8000`, não `8001`. O valor já configurado no `.env` continua prevalecendo. Essa troca de sintaxe preserva o endereço de publicação, a porta e o protocolo; não requer mudar redes, volumes ou expor o servidor em todas as interfaces. Os ZIPs de deploy futuros usam os mesmos templates. Alterar o código-fonte não modifica pacotes já publicados nem stacks já instaladas, e o ajuste do Compose não exige recompilar a imagem.

Para distinguir o painel de um problema na aplicação, consulte `docker compose ps app` e teste `http://127.0.0.1:<porta-configurada>/api/health` no próprio host Docker. Um endereço `127.0.0.1` aberto em outro computador aponta para esse outro computador; acesso remoto requer o proxy ou túnel autorizado para a instalação. Os cartões dos serviços opcionais podem continuar inativos enquanto seus perfis não estiverem habilitados.

## GHCR público ou autenticado

Uma publicação bem-sucedida e um pull anônimo são verificações diferentes. O [GitHub documenta](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) a publicação, a autenticação e os metadados de vínculo ao repositório. A [visibilidade do pacote](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility) pode exigir alteração por um administrador nas configurações do pacote, mesmo quando o repositório de fontes é público.

O manifesto registra `public_pullable` para cada imagem. A sonda anônima consulta o manifesto no Registry v2 sem usar o token do workflow. O pipeline também executa pull autenticado por digest, conferência do ID e smoke das imagens. Uma sonda anônima negativa não cancela o bundle offline nem afirma que o push falhou.

Se a imagem exigir credenciais, use uma conta autorizada e autentique sem inserir o token em arquivos versionados:

```sh
docker login ghcr.io
docker compose pull
docker compose up -d
```

Para consumo privado, o GitHub orienta token com permissão de leitura de pacotes (`read:packages`) e acesso à organização/pacote quando aplicável. A automação não usa endpoint inventado para mudar visibilidade. O campo `public_pullable` é diagnóstico do momento da publicação, não garantia permanente de disponibilidade externa.

## Imagens para uso offline

Baixe também `EscrituraIntegrada-<versão>-linux-amd64-images.tar.gz`, seu `.sha256` e `.manifest.json`. O arquivo inclui as seis imagens, sem depender do download de bases ou mirrors durante a instalação. Docker Engine/Desktop e Compose devem estar instalados previamente; o pacote de imagens não instala o Docker.

Confira a integridade:

```sh
sha256sum -c EscrituraIntegrada-<versão>-linux-amd64-images.tar.gz.sha256
docker load -i EscrituraIntegrada-<versão>-linux-amd64-images.tar.gz
# Antes do up: fixe as variáveis de imagens no .env nas referências de images.json.
# Em instalação nova, execute init com o nome do projeto e a tag versionada local do app.
docker compose up -d --pull never
```

No PowerShell, `Get-FileHash -Algorithm SHA256 <arquivo>` permite comparar o hash com o manifesto. `docker load` aceita o arquivo comprimido. Para fixar a publicação offline, altere somente ESCRITURA_IMAGE e REDIS_IMAGE, POSTGRES_IMAGE, MYSQL_IMAGE e MINIO_IMAGE no .env para os campos reference correspondentes de images.json. Preserve projeto, portas, dados e credenciais. O manifesto guarda digests e IDs para conferência; o tar contém as tags versionadas, não os canais móveis. Não é necessário outro Compose e não se depende da preservação de RepoDigests por docker save/load.

O exportador grava o tar comprimido por streaming. No runner isolado, `--verify-load` recusa containers em uso, remove somente as tags do manifesto, carrega o bundle, confere os IDs e executa novamente o smoke com `--pull never`. `offline_load_verified: true` só é escrito depois desse teste real. A ausência dessa marca significa que a carga ainda não foi demonstrada por esse artefato.

O app usa `pull_policy: always` nos três templates online (raiz, produção e develop), inclusive quando `ESCRITURA_IMAGE` aponta para `:develop` ou `:latest`. Isso consulta o registro durante pull/up mesmo com a tag em cache; uma referência versionada continua escolhendo a mesma release. Serviços opcionais mantêm `missing`. Offline, fixe as tags no .env e use `--pull never`: o tar contém a tag versionada, não os aliases móveis. Falhas de pull online não devem ser ocultadas usando silenciosamente imagens antigas.

## Ativar um serviço opcional

Os nomes dos perfis são `redis`, `postgres`, `mysql` e `minio`. Antes de ativá-los, preencha apenas as variáveis correspondentes no `.env` privado do ambiente.

| Perfil | Variáveis obrigatórias | Diretório relativo |
|---|---|---|
| Redis | `REDIS_PASSWORD`, mínimo 16 caracteres | `./data/<projeto>/redis` |
| PostgreSQL | `POSTGRES_PASSWORD`, mínimo 16; banco/usuário configuráveis | `./data/<projeto>/postgres` |
| MySQL | `MYSQL_ROOT_PASSWORD` e `MYSQL_PASSWORD`, mínimo 16 | `./data/<projeto>/mysql` |
| MinIO | `MINIO_ROOT_USER`, mínimo 3; `MINIO_ROOT_PASSWORD`, mínimo 16 | `./data/<projeto>/minio` |

Exemplo:

```sh
docker compose --profile redis up -d
docker compose --profile redis ps
```

Para iniciar mais de um perfil, repita `--profile`. Para uso offline, use `docker compose --profile redis up -d --pull never` (substitua/repita o perfil desejado). Gere senhas próprias, longas e aleatórias; os pacotes entregues deixam esses campos vazios. Caracteres especiais devem seguir a [sintaxe de `.env` do Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/); aspas simples evitam interpolar `$` na senha.

A validação fica no entrypoint de cada imagem e é executada apenas quando o serviço é iniciado. Assim, a configuração de app-only não exige segredos de perfis inativos. Isso evita exigir `${VAR:?}` para credenciais opcionais durante a fase global de interpolação. As senhas não são passadas por build args e não entram nas camadas das imagens.

Se um perfil for iniciado com credenciais ausentes, ele termina com código 64 e uma mensagem com os nomes das variáveis a preencher. O aplicativo mantém seu diretório SQLite e sua inicialização independentes. Não confunda a saúde do container de banco com uma integração funcional do aplicativo.

## Persistência, backup e atualização

O aplicativo grava `/data/escritura.sqlite3` em `./data/<COMPOSE_PROJECT_NAME>/app`, inclusive arquivos auxiliares de WAL quando ativos. Tudo em `/data` persiste no mesmo bind, incluindo documentos e relatórios. Nos templates novos os cinco serviços usam subpastas relativas distintas. Volumes nomeados de instalações antigas só são convertidos pelo procedimento administrativo explícito de [STORAGE.md](DOCKER_STORAGE.md); este código não migra automaticamente dados. O filesystem raiz do container é somente leitura, `/tmp` é temporário e o processo executa como UID/GID `10001`. O encerramento recebe prazo de 30 segundos.

Uma cópia consistente do SQLite pode ser criada pela API de backup do próprio SQLite, com o container em execução. O comando abaixo grava somente uma cópia no diretório de dados e usa a imagem já instalada:

```sh
docker compose exec -T app python -c "import sqlite3; s=sqlite3.connect('/data/escritura.sqlite3'); d=sqlite3.connect('/data/backup.sqlite3'); s.backup(d); d.close(); s.close()"
docker compose cp app:/data/backup.sqlite3 ./backup.sqlite3
```

Esse nome substitui a cópia anterior; renomeie o arquivo externo com a data e mantenha backups fora do diretório da stack. Proteja os arquivos, pois contêm dados do escritório. Teste restauração em um projeto/volume separado antes de depender do procedimento. Não copie apenas o `.sqlite3` enquanto há gravações sem usar um mecanismo consistente.

Antes de atualizar: guarde backup, preserve o `.env` e o nome do projeto Compose do ambiente e revise a versão de destino. Em produção, altere `ESCRITURA_IMAGE` para a tag publicada e execute `docker compose up -d`.

### Atualizar canais móveis no Compose e Dockge

`ESCRITURA_IMAGE=ghcr.io/codisplanfiscalai/escritura-integrada:develop` acompanha a pré-release; `ghcr.io/codisplanfiscalai/escritura-integrada:latest` acompanha a main estável. O pacote develop já escolhe `:develop`; o pacote de produção mantém a tag versionada até o operador optar por `:latest`. Somente o app usa `pull_policy: always` em todos os templates online.

`docker compose up -d` consulta o registro e recria o app se a imagem mudou, sem trocar o `.env` a cada versão. `docker compose pull app` apenas baixa a imagem; execute `up -d` para aplicá-la. Não há atualização contínua em segundo plano. Reiniciar um container existente também não busca outra imagem. No Dockge, salve o Compose usado pela stack e execute a ação de atualizar/implantar que faz pull/up. Resolva falhas de rede/autenticação antes de atualizar; não use opções de ignorar falhas de pull ou `--pull never` no fluxo online.

**Stacks já instaladas, inclusive as criadas pelo Compose da raiz/produção:** incorpore uma única vez `services.app.pull_policy: always` no Compose efetivamente usado pela stack. Se quiser acompanhar um canal, ajuste também `ESCRITURA_IMAGE` para uma das referências acima. Com `missing`, uma imagem em cache pode levar `docker compose pull app` a informar `Skipped Image is already present locally`, e recriar o container mantém a imagem antiga. O novo código e os futuros ZIPs não modificam stacks existentes nem assets de releases já publicados.

Não substitua todo o `.env` pelo exemplo: preserve credenciais, nome de projeto, bind, portas e volumes. Copiar um ZIP novo sobre a instalação pode apagar configurações privadas. Não mude o projeto existente para `escritura-develop`: isso apontaria para outro conjunto de dados.

O workflow de release promove o alias no job final **Promover alias develop após publicação**, somente em develop e depois de todos os gates e da publicação. Esse job usa a imagem já construída, exige a mesma versão, commit, execução e recibos dos assets, confere o inventário remoto e valida o pull público por digest. A prova é repetida imediatamente antes e depois da gravação. As referências main/latest são conferidas e não são escritas por esse job. Imagens opcionais continuam fixadas por conteúdo e requerem atualização deliberada do pacote/configuração.

Aguarde também esse job final ficar verde antes de atualizar uma instalação pelo canal. A presença da release ou da tag SemVer sozinha não comprova que `:develop` avançou. O artefato `develop-alias-report` registra o resultado. Em erro de rede durante a gravação, o resultado pode ser incerto: confira o digest corrente antes de repetir. É possível reexecutar apenas o job final da mesma run, sem reconstruir as imagens, desde que o head, os gates mais recentes, os assets e os recibos continuem válidos. Uma nova execução de workflow não substitui essa reexecução. O job não tenta desfazer alterações externas nem muda `latest`, reservado a main/estável.

### Fixar uma release ou fazer rollback

Guarde o pacote e o bundle da release desejada. Após verificar backup e compatibilidade do banco, copie somente as referências de images.json para as variáveis de imagens no .env. Execute docker compose up -d. Offline, carregue o tar correspondente e acrescente --pull never. Não substitua o .env inteiro nem altere projeto, credenciais, portas e volumes.

Para retomar o canal, altere ESCRITURA_IMAGE no .env para :develop ou :latest e execute docker compose up -d. Não é necessário down para atualizar. Nunca use down -v para atualizar: ele remove volumes, inclusive a chave separada do A1. Um rollback de imagem não desfaz migração de dados. Os perfis opcionais exigem seus backups nativos; backup SQLite não os inclui.

## Build, versões e verificações

`docker/images.lock.json` fixa as bases por tag **e digest**, conferidos por resposta da API oficial do registro e SHA-256 dos bytes do manifesto. Na verificação de 2026-11-07: Python `3.12.16-slim-bookworm`, Node `24.22.2-bookworm-slim`, Redis `8.2.11-bookworm`, PostgreSQL `17.11-bookworm`, MySQL `8.4.13-oraclelinux9` e Go `1.26.10-bookworm`. Essa lista registra os insumos escolhidos; não é promessa de que continuarão sendo as versões mais recentes ou sem vulnerabilidades.

`docker/runtime.lock` fixa as 25 dependências Python diretas/transitivas do runtime Linux e o `colorama` com marcador exclusivo de Windows, com hashes oficiais de wheels, preservando as versões do ambiente de aplicação já testado. O build exige binários, hashes e `pip check`. `frontend/package-lock.json` e `npm ci` travam o frontend. Node e Go ficam nos estágios de compilação. MinIO é compilado do commit e arquivo de fonte com checksum, com módulos fixados no `go.sum`, `go mod verify` e `GOTOOLCHAIN=local`.

A publicação calcula IDs de conteúdo para bases/mirrors e usa tags que incluem esse hash. A tag SemVer da aplicação é imutável pelo publicador: uma tag existente precisa ter o mesmo ID de conteúdo e commit; divergência interrompe o processo. Mudanças de conteúdo exigem nova versão. O deploy develop escolhe o alias móvel `develop`; produção escolhe uma tag versionada por padrão e permite optar por `latest` da main estável. Somente a aplicação acompanha esses canais; imagens auxiliares permanecem fixadas por conteúdo. O source SHA, versão, digests, IDs, resultado do smoke e disponibilidade anônima compõem o manifesto da publicação.

Comandos do pipeline, depois de aplicar a versão no checkout:

```sh
python scripts/build_images.py validate --version <SemVer> --channel develop --revision <SHA-completo> --output artifacts/images-validated.json
python scripts/build_images.py publish --version <SemVer> --channel develop --revision <SHA-completo> --output artifacts/images-published.json
python scripts/package_deploy.py --version <SemVer> --channel develop --images-manifest artifacts/images-published.json --output-dir artifacts/release
python scripts/export_images.py --images-manifest artifacts/images-published.json --output artifacts/release/EscrituraIntegrada-<SemVer>-linux-amd64-images.tar.gz --verify-load
```

`validate` não publica. `--dry-run` gera somente um plano, com status `planned`; o empacotador recusa esse plano como publicação. O modo `publish` é orquestrado pelo workflow somente após os gates Linux/Windows. A base é enviada para ser usada por digest; app e serviços são enviados após seu smoke real. O builder `default` usa o driver Docker local, permitindo ao modo de validação resolver a base recém-construída sem publicar em PRs.

O smoke confere dependências da base; health/versão/modo sem demo; HTML, JavaScript e CSS compilados; criação de administrador sem senha predefinida; persistência de sessão e SQLite após reinício; processo sem root; credenciais obrigatórias e health dos quatro serviços; ausência de portas host nesses serviços. O smoke de armazenamento também prepara binds, copia friamente os cinco volumes de fixtures para diretórios novos, confere seus inventários e testa persistência após recriação e leitura dos volumes originais. A avaliação visual/funcional das telas continua sendo uma etapa própria, além desses checks técnicos.

Para manutenção do catálogo, confira novas versões/digests oficiais, regenere o lock quando necessário e execute `python scripts/sync_deploy_templates.py`. O modo `--check` identifica exemplos desatualizados sem editar, incluindo os binds relativos e a política de pull do app. Não há atualização silenciosa de versão upstream, pacote Python ou imagem já publicada.

## Limites da validação e materiais excluídos

Os testes estáticos verificam catálogo, segredos vazios, isolamento dos ambientes, pacotes por allowlist, imutabilidade e erros de guard. Build, execução real Docker e carga do bundle são atestados apenas pelos resultados do CI que executou esses passos. Não se deve descrever um teste Docker como aprovado apenas porque uma inspeção estática passou.

O contexto de build usa allowlist em `.dockerignore`. Pacotes de deploy têm lista fechada de arquivos. Binários e código recuperados, prints de terceiros, bancos, logs de execução, credenciais e pastas de análise não entram nos artefatos Docker/deploy. Os componentes de terceiros e o caso de distribuição por fonte do MinIO estão documentados em [THIRD-PARTY.md](../docker/THIRD-PARTY.md).

Referências técnicas: [perfis Compose](https://docs.docker.com/compose/how-tos/profiles/), [interpolação](https://docs.docker.com/reference/compose-file/interpolation/), [serviços e pull policy](https://docs.docker.com/reference/compose-file/services/), [docker image save](https://docs.docker.com/reference/cli/docker/image/save/), [docker image load](https://docs.docker.com/reference/cli/docker/image/load/), [release MinIO utilizado](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z).

A base inclui `libarchive-tools` e `libarchive13` Debian Bookworm `3.6.2-1+deb12u5` para RAR comprimido. A versão vem do [repositório oficial Debian](https://packages.debian.org/bookworm/libarchive-tools) e participa da identificação da imagem base. Novas correções exigem atualizar o Dockerfile e regenerar os manifests.


### Aliases GHCR e promoção estável

O job `promote-latest` publica apenas o alias da aplicação `latest`, depois da
release **main** concluída e dos sete gates aprovados. Ele reutiliza o manifesto
OCI versionado, sem rebuild, e verifica SHA da main, versão estável, execução,
assets/checksums, digest e leitura pública. Não altera a branch nem o alias
`develop`. O job existente `promote-develop` continua restrito à pré-release.

A sincronização automática main → develop aguarda `promote-latest`, evitando
alterar o snapshot protegido durante a promoção. Uma falha de promoção mantém
o relatório `latest-alias-report` e impede essa sincronização para uma nova
release. O re-run do job final confere novamente as provas e não duplica PUT se
o alias já tiver o digest correto. Não há rollback automático de um PUT com
resultado incerto; o relatório exige conferência do estado antes de nova ação.

Isso vale para novas releases cujo workflow inclua o job. Releases históricas
já publicadas não são reconstruídas nem alteradas por esse acréscimo; uma
recuperação de alias antigo usa o procedimento operacional explícito existente.
