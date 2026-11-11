# Recuperação única de 0.8.0-dev.21

Este fluxo operacional não faz parte do release normal. Só é disparado por push na branch `ops/recover-release-dev21`; não tem entrada genérica de versão/SHA ou acionamento manual. Revisar o diff antes de publicar essa branch. O push iniciará a recuperação e, se ela concluir, a promoção de `:develop`.

## Identidades congeladas

- Fonte: `1c686036d7e337632a7eb7b204b016063f6df32f`.
- Execução original: [42978878696, tentativa 2](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/42978878696/attempts/2).
- A execução original continua registrada como **failure**. Os seis gates (reserva, Linux, Windows, duas arquiteturas macOS e Docker) foram aprovados. Apenas a etapa de montagem dos assets falhou; o passo de publicação da release foi pulado.
- Plano revisável: `.github/recovery-dev21.json`, com os IDs, SHA-256 e tamanhos dos nove ZIPs originais, heads esperados de develop/main, digest app e digest intocado de latest.
- O backup durável dos 39 assets dev.20 foi restaurado e verificado integralmente antes deste plano. O inventário público e o SHA-256 do arquivo restaurado estão no plano. IDs privados e credenciais não são publicados.

## Operação

1. Obter os heads e a tentativa original da API GitHub. Recusar fonte, main, workflow, gates, falha ou branch operacional diferentes dos aprovados.
2. Conferir a release dev.20 e seu inventário completo contra o backup. Qualquer asset adicional, ausente ou alterado bloqueia a operação.
3. Fazer checkout **separado** e exato da fonte. O código operacional não é copiado para essa fonte e não entra no ZIP de fontes.
4. Baixar os ZIPs por ID, validar metadados/proveniência, tamanho e SHA-256. O token efêmero só vai a `api.github.com`; o destino HTTPS de blob recebe uma nova requisição sem credenciais e não pode redirecionar novamente. A extração recusa caminhos inseguros, symlinks e sobrescritas.
5. Extrair `browser-evidence` em `artifacts/reports`, preservando `browser/report.json` e `browser-workspace-tabs/report.json` como irmãos. O restante mantém o layout original.
6. Puxar as seis imagens existentes por digest. Conferir ID e plataforma, atribuir apenas tags **locais** exigidas pelos scripts originais e regenerar somente Compose e o arquivo offline. O verificador original de carga offline roda com essas imagens; não há rebuild nem reexecução dos gates normais Linux, Chromium, Windows, macOS ou Docker build.
7. Executar os scripts originais `package_deploy.py`, `export_images.py --verify-load` e `scripts.ci.artifacts` a partir do checkout testado. O assembler confere os relatórios, os hashes dos binários, Compose e offline, gera inventário/SHA256SUMS e usa `git archive` no SHA original.
8. Revalidar guardas, backup e `latest`; chamar o publisher original com o plano original. Sua exclusão é encapsulada para aceitar somente os 39 IDs respaldados e revalidar a identidade de cada asset imediatamente antes de excluí-lo. Não são removidos assets desconhecidos.
9. Comparar todos os assets remotos publicados com os bytes locais por nome, tamanho, estado e digest. Acrescentar ao corpo da release o link verificado da recuperação, sem falsificar o status da execução original. Publicar `recovery-proof.json` com inventário e procedência.
10. Em job dependente, verificar novamente fonte/main, execução original, release/tag/marker, receipt e sucesso do job de recuperação. Promover exclusivamente `:develop`, usando os bytes do manifesto já existente. Verificar digest, image ID, plataforma, labels e pulls reais anônimos. Conferir `:latest` antes e depois, sem fazer PUT nele.

O lock `escritura-release-mutations` cobre ambos os jobs e coordena com as mutações normais. Permissões: `contents:write` e `actions:read` para recuperação; `contents:read`, `actions:read`, `packages:write` para o alias. Não são criados secrets e o checkout não persiste credenciais.

## Falhas e reexecução

Não executar o workflow normal de novo: ele repetiria a falha de extração e reconstruiria artefatos sem necessidade. Este fluxo falha de forma conservadora se a release já saiu de dev.20 ou se o inventário mudou. Uma falha depois da publicação parcial exige inspecionar release, receipt e digest antes de preparar qualquer retomada; não fazer rerun cego, remover assets nem sobrescrever o plano para passar pelas guardas. A promoção é idempotente quando `:develop` já possui o digest esperado, mas continua exigindo todas as provas.

A verificação local testa guardas e contratos sem efetuar uploads ou alterações remotas. O sucesso operacional só pode ser afirmado depois dos dois jobs e das verificações externas.
