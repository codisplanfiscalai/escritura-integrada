# Implantação — production

Use preferencialmente o ZIP de deploy de uma release: ele inclui `.env` preenchido com tags publicadas. Para trabalhar a partir deste diretório, copie `.env.example` para `.env` e informe a imagem da release.

```sh
docker compose up -d
docker compose ps
```

Somente a aplicação publica uma porta, em `127.0.0.1:8000`. O primeiro acesso solicita a criação do administrador. Produção e desenvolvimento usam projetos e volumes separados.

Perfis opcionais: `redis`, `postgres`, `mysql`, `minio`; exigem credenciais próprias. Nenhum deles substitui o SQLite nem já está conectado ao aplicativo. Consulte [DEPLOY.md](../../docs/DEPLOY.md) para imagens offline, backups, limites e licenças.
