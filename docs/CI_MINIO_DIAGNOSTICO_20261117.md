# MinIO: falha de resolução e diagnóstico preservando os gates

## Evidência do incidente

Run `44018567435`, publicação develop/dev.45 após merge PR73. O job
`133826540269` resolveu a tag auxiliar MinIO às 04:50:53 UTC, conferiu o
descritor e fez pull do digest
`sha256:eeb643c7e3a147c0b0455f42d8968e702bd7aecd0a4977ccd7df62a4afd41285`.
O smoke do MinIO passou nessa etapa.

No job publish `133827999990`, `remote_exists` encontrou a mesma tag, mas
`docker buildx imagetools inspect --raw` retornou erro às 04:55 UTC. A mensagem
genérica de `pinned_remote` descartou o stderr capturado. Portanto não é possível
atribuir retrospectivamente uma causa específica a rede, credenciais, registry,
manifesto ou digest. Acessibilidade no validate não prova acessibilidade depois.

Não consta `docker push` no log desse job. Ele falhou antes do smoke e dos pushes
finais; promoção develop e registro de publicação foram ignorados. Não foi
demonstrada publicação dev.45 concluída nem alteração do alias pelo run.

## Mudança local limitada

Os erros de consulta de imutabilidade, resolução do manifesto e resolução do
descritor passam a incluir somente etapa, returncode, categoria reportada,
eventuais códigos HTTP e hash da saída capturada. Os rótulos são indícios do
comando, não causa comprovada. O classificador examina no máximo 16.384 caracteres.

Não se imprime stdout/stderr bruto, credenciais, URLs com parâmetros ou conteúdo
arbitrário do registry. Saída desconhecida fica `unclassified`; não se transforma
em autorização, sucesso ou evidência de ausência de imagem. O tratamento de tag
ausente existente não foi ampliado.

Não há retry automático, fallback de publicação, reconstrução/sobrescrita de tag,
mudança de credenciais/permissões, novo workflow, dispatch, push de imagem ou
promoção de alias. Digest, bytes do manifesto, plataforma, labels, handoff do
mesmo run e smoke seguem obrigatórios. Falha do descritor também continua bloqueando,
agora com identificação de etapa em vez de erro genérico de subprocesso.

## Validação e limites

10 testes novos sintéticos cobrem categorias, sigilo, limite de classificação,
falha persistente sem retry/escrita, cache opcional sem atestação, falha de descritor,
manifesto inválido/index e digest divergente. Sucessos preservam o digest dos bytes
originais, inclusive manifesto com newline.

```sh
PYTHONPATH=tests:. python -m unittest test_image_remote_diagnostics \
  test_ci_delivery_cache test_infrastructure test_ci_release \
  test_develop_alias test_image_aliases -q
```

Resultado: 121 testes passaram, sem falhas/erros/skip; py_compile e diff-check
passaram. Docker/Podman não estão disponíveis neste executor; não houve sonda
atual ao GHCR, reprodução de registry ou publicação. Isso é uma melhoria de
diagnóstico testada localmente, não a correção comprovada do incidente.

Composição final aplicada sem conflitos em checkout isolado diretamente sobre
develop `4c71b55619cebe470df48d2264a150a9157c04df`, dev.45. Os 121 testes,
compilação e diff-check foram repetidos nessa composição. O delta contém somente
este documento, o diagnóstico em `build_images.py` e seus testes sintéticos;
não incorpora commits ou arquivos das branches paralelas de recepção/API.
A aplicação completa, Docker e PostgreSQL real não foram executados localmente.
Nenhum dado real ou arquivo privado integra o patch. CI remota deve ser conferida
no head efetivamente publicado antes de qualquer merge ou nova release.
