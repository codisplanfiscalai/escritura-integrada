# Componentes de terceiros nas imagens

As imagens com prefixo `escritura-integrada` são distribuições mantidas neste repositório. Os nomes Redis, PostgreSQL, MySQL, MinIO, Python, Node.js e Go continuam identificando seus respectivos projetos; não indicam patrocínio ou aprovação deles.

O catálogo [images.lock.json](images.lock.json) registra referências upstream, versões, digests e fontes. Os conteúdos desses componentes e das distribuições Linux permanecem sujeitos às respectivas licenças; a licença do código deste repositório não os relicencia. Os mirrors preservam as camadas upstream e acrescentam apenas a validação de credenciais e metadados do pacote.

| Componente | Origem e avisos |
|---|---|
| Python / Debian | [Docker Official Image](https://github.com/docker-library/python), [licença Python](https://docs.python.org/3/license.html), avisos Debian em `/usr/share/doc` quando presentes no upstream |
| Dependências Python | Distribuições PyPI e seus arquivos `*.dist-info/licenses`, `LICENSE` e metadados; versões e hashes em `runtime.lock` |
| Node.js / npm / frontend | [Node.js](https://github.com/nodejs/node/blob/main/LICENSE); dependências do frontend com `package-lock.json`; Node/npm são usados somente na compilação |
| Redis 8 | [Licenciamento oficial](https://redis.io/legal/licenses/): opções AGPLv3, RSALv2 ou SSPLv1; [fonte Redis](https://github.com/redis/redis), [empacotamento oficial](https://github.com/redis/docker-library-redis) |
| PostgreSQL | [Licença PostgreSQL](https://www.postgresql.org/about/licence/), [empacotamento oficial](https://github.com/docker-library/postgres) |
| MySQL Community | [Fonte e licenças](https://github.com/mysql/mysql-server), [empacotamento oficial](https://github.com/docker-library/mysql); avisos upstream preservados |
| Go | [Licença](https://go.dev/LICENSE); usado somente para compilar o MinIO |
| MinIO Community | AGPL-3.0-or-later; [LICENSE no commit utilizado](https://github.com/minio/minio/blob/9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a/LICENSE) |

## MinIO: fonte correspondente e construção

Esta distribuição compila o release oficial `RELEASE.2025-10-15T17-29-55Z`, commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`. O arquivo de origem é verificado por SHA-256 `45521908307306e925c98d629e1c17d78c8b72b6ee242b1bfb1409f7d8ee5841`. O código funcional upstream não é alterado; a compilação usa metadados fixos e o wrapper de inicialização deste repositório exige credenciais explícitas.

O arquivo de fonte completo está em `/usr/share/minio-source/source.tar.gz` dentro da imagem e a licença em `/usr/share/licenses/minio/LICENSE`. O [arquivo oficial do commit](https://codeload.github.com/minio/minio/tar.gz/9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a) e os scripts necessários para reconstrução permanecem identificados em `docker/minio.Dockerfile`, `docker/minio-entrypoint.sh`, `docker/images.lock.json` e `scripts/build_images.py` deste repositório.

A [página oficial do release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z) informa uma correção de segurança e orienta compilar containers a partir do fonte. O [README oficial](https://github.com/minio/minio) informa distribuição comunitária somente por fonte e ausência de manutenção do repositório. Por isso, a imagem aqui gerada não é anunciada como uma imagem oficial atualizada do fornecedor nem como um serviço já integrado à aplicação.

Os componentes opcionais não são necessários para usar o aplicativo SQLite. A eventual inclusão de novos serviços ou modificações deve preservar os avisos, os termos aplicáveis e a disponibilidade do fonte correspondente quando exigida pela licença escolhida.
