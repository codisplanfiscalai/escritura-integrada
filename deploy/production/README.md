# Implantação — production

Use preferencialmente o ZIP de deploy de uma release: ele inclui `.env` preenchido com tags publicadas. Para trabalhar a partir deste diretório, copie `.env.example` para `.env` e informe a imagem da release.

```sh
docker compose up -d
docker compose ps
```

O app usa `pull_policy: always`: pull/up consulta o registro mesmo com imagem em cache, inclusive ao usar `:develop` (pré-release) ou `:latest` (main estável). Produção mantém uma tag versionada por padrão. Em stacks antigas, incorpore `services.app.pull_policy: always` no Compose usado pela stack, preservando `.env`, projeto e volumes. Código/ZIP novo não atualiza a stack instalada. No Dockge, salve a alteração e execute atualizar/implantar com pull/up; reiniciar o container não basta. Não há atualização contínua automática. O override `compose.release.yaml` mantém as imagens fixadas e a política para offline/rollback.

Somente a aplicação publica uma porta, em `127.0.0.1:8000`. O primeiro acesso solicita a criação do administrador. Produção e desenvolvimento usam projetos e volumes separados.

Perfis opcionais: `redis`, `postgres`, `mysql`, `minio`; exigem credenciais próprias. Nenhum deles substitui o SQLite nem já está conectado ao aplicativo. Consulte [DEPLOY.md](../../docs/DEPLOY.md) para imagens offline, backups, limites e licenças.
