# Implantação — production

Use preferencialmente o ZIP de deploy de uma release: ele inclui `.env` preenchido com tags publicadas. Para trabalhar a partir deste diretório, copie `.env.example` para `.env` e informe a imagem da release.

**Stack já instalada com volumes nomeados:** siga a [migração de armazenamento](../../docs/DOCKER_STORAGE.md) antes de trocar mounts. Pastas vazias não recebem os dados dos volumes antigos automaticamente.

Se já usa `./data/app:/data`, preserve esse mount e seu Compose atual, sem init ou nova cópia do volume guardado. Veja a rota de bind existente na documentação e o override explícito `deploy/compose.existing-bind.yaml` (no ZIP, ao lado do Compose).

O template atualizado aceita `ESCRITURA_APP_DATA_BIND=./data/app` no `.env`; vazio usa o padrão por projeto. Valide acesso com `deploy_storage.py check-app` antes de recriar um app existente, conforme [permissões e health](../../docs/DOCKER_STORAGE.md#pré-validação-e-incidente-de-permissões-no-bind-do-app). O helper usa o USER da imagem instalada e não faz chown automático. Após subir, use `--require-health --wait-health-seconds 120` e confira os dados na interface; `Started` sozinho não comprova recuperação.

Instalação nova: no diretório da stack, baixe/carregue a imagem e execute a ferramenta `scripts/deploy_storage.py` do checkout (ou `deploy_storage.py` do ZIP) com `init --project <nome-exato-do-.env> --helper-image <imagem-local-do-app>`. O app e os perfis usam `./data/<COMPOSE_PROJECT_NAME>/<serviço>`, com diretórios preparados explicitamente e permissões próprias; não use chmod 777.

```sh
docker compose up -d
docker compose ps
```

O app usa `pull_policy: always`: pull/up consulta o registro mesmo com imagem em cache, inclusive ao usar `:develop` (pré-release) ou `:latest` (main estável). Produção mantém uma tag versionada por padrão. Em stacks antigas, incorpore `services.app.pull_policy: always` no Compose usado pela stack, preservando `.env`, projeto e volumes. Código/ZIP novo não atualiza a stack instalada. No Dockge, salve a alteração e execute atualizar/implantar com pull/up; reiniciar o container não basta. Não há atualização contínua automática. O override `compose.release.yaml` mantém as imagens fixadas e a política para offline/rollback.

Somente a aplicação publica uma porta, em `127.0.0.1:8000`. O primeiro acesso solicita a criação do administrador. Produção e desenvolvimento usam projetos e diretórios de dados separados.

Perfis opcionais: `redis`, `postgres`, `mysql`, `minio`; exigem credenciais próprias. Nenhum deles substitui o SQLite nem já está conectado ao aplicativo. Consulte [DEPLOY.md](../../docs/DEPLOY.md) para imagens offline, backups, limites e licenças.
