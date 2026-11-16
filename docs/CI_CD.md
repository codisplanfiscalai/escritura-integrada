# Integração, versões e distribuição

O repositório usa `main` para versões estáveis e `develop` para entregas de desenvolvimento. `main` conserva validações e distribuição completas. Temporariamente, `develop` entrega somente GHCR, conforme a política versionada descrita abaixo. A aplicação, os pacotes nativos quando habilitados e a imagem principal recebem a mesma SemVer. A existência destes arquivos de automação, por si só, não comprova que uma execução remota terminou: os resultados são registrados nos jobs, nos relatórios e no manifest de cada release.

## Workflows e permissões

| Arquivo | Disparo | Resultado | Permissões de escrita |
|---|---|---|---|
| `ci.yml` | PR para `main` ou `develop` | Testes, frontend/navegador e validação das seis imagens; Windows/macOS somente fora da pausa de develop; sem publicação | Nenhuma permissão de escrita no repositório ou no GHCR |
| `release.yml` | Push em `main`/`develop` ou execução manual | Commit de versão, gates e GHCR; bundles/release completos em main ou com desktop retomado; sincronização após main | `contents: write` nos jobs que alteram refs/releases; `packages: write` somente em publicação; `actions: write` somente para dispatch e limpeza de caches em job separado |
| `cache-cleanup.yml` | Diariamente às 04:23 UTC na branch padrão; manual em `main`/`develop`; também ao terminar release confiável | Plano ou exclusão limitada de caches elegíveis, com relatório | `actions: write`; não exclui releases |

As actions externas estão fixadas por SHA, com a versão correspondente em comentário. Os runners são `ubuntu-24.04` e `windows-2022`; a construção usa Python 3.12 e Node.js 24. PRs usam `pull_request`, sem credenciais de publicação. Não há `pull_request_target` executando código do autor com token de escrita.

## Pausa temporária de desktop em develop

`scripts/ci/delivery_policy.py` mantém `DEVELOP_DESKTOP_ENABLED = False`. PRs cuja **base** é `develop` não iniciam jobs Windows/macOS, não compilam instaladores e não executam seus smokes. PRs para `main` e outras bases continuam com a cobertura nativa completa. Linux, suite Python, testes de frontend/navegador, PostgreSQL de teste e smokes Docker continuam nas PRs conforme seus jobs existentes.

No push de `develop`, o plano grava `delivery_mode=ghcr_only`. A publicação exige Linux e Docker aprovados e os jobs nativos explicitamente `skipped`; falha/cancelamento nativo nunca equivale a sucesso. Não baixa/distribui ZIP, EXE ou PKG, não monta bundles offline e não cria/atualiza a pré-release GitHub. Publica as seis imagens por versão/digest, mantém seus smokes e promove somente o alias OCI `develop`. O recibo `escritura-ghcr-publication/1` identifica versão, SHA, run/tentativa e hash integral do manifesto de imagens. A promoção revalida contexto confiável, gates da mesma execução, head atual, leitura pública/digest/config da imagem e preservação de main/latest. Releases e assets históricos existentes não são removidos por essa pausa; nenhuma nova versão nativa é disponibilizada.

`main` sempre usa `delivery_mode=full`: exige Windows x64 instalado, macOS arm64/x64 instalado/atualizado, Linux e Docker, inventário/hashes, carga offline e publicação estável; a pausa não autoriza pular nenhum desses gates. Retomar develop exige mudar a constante para `True` em PR revisada e validar o fluxo completo. Não há flag de execução manual que contorne essa política.

**Limite temporário de cobertura:** PRs para develop deixam de provar empacotamento, instalação, integração gráfica e encerramento nativos Windows/macOS. Sucesso em Linux/Docker não atesta essas plataformas. As PRs abertas devem integrar esta alteração sequencialmente após sua aprovação/merge, para usar o novo workflow; execuções antigas continuam com o código antigo. Não cancelar nem repetir publicação de resultado incerto.

## Política SemVer

| Situação | Exemplo | Comportamento |
|---|---|---|
| Primeira versão estável | `0.4.0` | Tag `v0.4.0`, release estável e assets com `0.4.0` |
| Desenvolvimento posterior | `0.4.1-dev.12` | Durante a pausa, imagens GHCR versionadas e alias OCI `develop`; depois da retomada, também release/tag GitHub |
| Promoção de desenvolvimento | `0.4.1` | O sufixo é retirado em `main`, gerando nova tag estável |
| Novo código com versão já reservada | `0.4.1` → `0.4.2` | Incrementa patch; não reutiliza uma tag para outro commit |
| Incremento explícito maior | `0.5.0-dev.20` | Preserva o novo major/minor quando superior à linha estável |
| Conferência de PR | `0.4.1-pr.7.15` | Carimbo apenas no checkout temporário; sem commit, tag ou publicação |

O contador `-dev.N` pertence ao núcleo SemVer, não a `github.run_number`. Depois de publicar `0.8.0`, o próximo ciclo inicia em `0.8.1-dev.1` (ou em um major/minor explicitamente maior, também com contador inicial 1). Novos builds do mesmo ciclo incrementam N acima do manifest, do marcador publicado e das reservas no histórico de commits de preparação, inclusive execuções que falharam; uma repetição da mesma execução reutiliza o número já preparado. `-dev.0` é apenas o estado interno de sincronização, nunca uma distribuição publicada. Versões/imagens antigas não são renumeradas nem sobrescritas. O número global do workflow permanece nos recibos apenas para rastreabilidade. A base de `develop` é pelo menos o próximo patch da versão de `main` e das tags estáveis já reservadas. Não são criadas tags para cada `-dev.N`: existe um único marcador `develop`. O ZIP de fontes e o manifest fixam o commit de cada entrega, pois o marcador muda.

O script grava `VERSION`, `app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json` e `package.json`; sincroniza também `package-lock.json` da raiz caso exista. Ele modifica somente a versão do projeto, incluindo a entrada raiz de `packages` no lock. Preserva scripts de construção e versões das dependências. A interface lê a versão do manifest do frontend.

Depois da publicação estável, a sincronização integra `main` em `develop`, prepara uma versão superior e dispara explicitamente o próximo pipeline. Entre o início dessa transição e a conclusão dos novos gates, a pré-release anterior continua disponível; o marcador é atualizado apenas quando a nova distribuição foi conferida.

## Sequência de publicação completa (`delivery_mode=full`)

1. **Preparar:** verifica que o evento ainda representa o head da branch, calcula a SemVer e cria somente o commit dos manifests que mudaram. O head avança sem `force`. A execução registra o SHA resultante no plano `ci-plan.json`.
2. **Linux:** confere todos os manifests, instala o runtime pelo lock com hashes, compila a interface e seus avisos de terceiros, executa os testes de dia civil do frontend, a suite Python e a compilação sintática. O frontend distribuído ao Windows sai deste job.
3. **Windows:** repete a suite Python com o runtime comum, confere a ausência de alterações rastreadas e gera o pacote x64. O smoke extrai o ZIP em caminho com espaços/Unicode, abre o executável gráfico, verifica a área de trabalho renderizada, versão/API e encerramento. Processos remanescentes ou encerramento forçado reprovam o gate. JSON, captura e logs ficam nos artefatos da execução.
4. **Docker:** constrói/reutiliza e testa localmente as seis imagens `linux/amd64`, sem login/push. Valida a aplicação e os perfis opcionais, inclusive os arquivos Compose reais. O builder `default`, com driver Docker, permite resolver a base local nesta etapa.
5. **Reservar e publicar:** após os três gates e nova checagem do SHA, reserva a tag estável imutável, quando aplicável, e autentica no GHCR. Recebe as imagens já validadas do mesmo run, confere identidade/proveniência, publica/reutiliza por digest e testa as imagens exatas e verifica pull autenticado. Uma sonda anônima registra `public_pullable` separadamente.
6. **Conferir os bundles:** gera os dois pacotes Compose, exporta as imagens, remove somente suas tags no runner isolado e executa `docker load`. Confere os IDs e repete o smoke com `--pull never`. A montagem dos assets exige que todos os relatórios correspondam à versão/commit e verifica hashes.
7. **Finalizar a release:** envia os arquivos, verifica os uploads e volta a conferir o head antes da publicação final. A release estável publicada nunca tem seus assets substituídos por este fluxo. A pré-release atualiza o marcador `develop` e remove somente assets antigos da própria aplicação nessa release.
8. **Sincronizar:** quando a origem é `main`, integra a branch em `develop` e executa `workflow_dispatch`. Esse dispatch é necessário porque pushes feitos com `GITHUB_TOKEN` normalmente não iniciam outro workflow de push.

O número estável é reservado **depois dos gates e antes do primeiro push OCI**. Se houver um novo push de código durante a publicação das imagens, o guard impede finalizar a release antiga e o próximo run escolhe outro patch. A reserva evita tentar sobrescrever uma tag OCI que já recebeu conteúdo. Uma reserva pendente não é apagada nem redirecionada; ela pode ser retomada no mesmo commit.

## Merge entre as branches

A sincronização usa um worktree temporário e `git merge --no-commit --no-ff`. A árvore final é calculada pelo Git, preservando a ancestralidade e os hotfixes de `main`. Não se fabrica um merge commit com a árvore antiga de `develop`.

Quando um conflito envolve um manifest de versão, o script normaliza somente o número do projeto nas três etapas e repete o merge textual. Mudanças compatíveis de dependências/scripts permanecem. Conflitos reais nesses campos, exclusões conflitantes ou arquivos de código fora da lista permitida interrompem a sincronização e exigem resolução manual. Não há escolha automática generalizada de `ours`/`theirs`.

Os testes locais de CI exercitam dois ciclos de promoção → versão estável → sincronização → nova promoção, preservação de hotfixes e interrupção de conflitos de código/dependências. A proteção de branch continua sendo respeitada: se impedir o commit do bot, o job falha com diagnóstico; o script não altera proteções ou permissões.

## Concorrência, integridade e recuperação

Cada branch possui uma fila de workflow sem cancelamento da execução corrente. Os jobs que alteram refs, registry ou releases compartilham um grupo de exclusão. `queue: max` permite enfileirar até 100 pendentes; uma execução antiga ainda precisa passar pelo guard de SHA antes de cada fase de publicação relevante. O workflow de caches usa o mesmo grupo para não coincidir com a mutação de uma release.

Somente `refs/tags/develop` pode usar atualização forçada. Heads `main`/`develop` e tags estáveis nunca usam `force`. A imutabilidade estável descrita aqui é a política imposta pelos scripts; não se habilita automaticamente uma política global do GitHub que impeça mover a pré-release. Administradores continuam responsáveis pelas regras de acesso ao repositório.

Os arquivos da nova pré-release são enviados e conferidos antes de mudar seu marcador. As APIs de tag/release não oferecem uma transação única; se a atualização dos metadados falhar, o script tenta restaurar a tag anterior apenas quando ela ainda aponta para o alvo desta execução. Arquivos preparados podem permanecer ao lado dos anteriores até a próxima publicação bem-sucedida. O manifest versionado identifica o conjunto correto.

Uma falha de upload deixa a release em rascunho quando ela ainda não foi publicada. A consulta procura também rascunhos na listagem autenticada, permitindo retomar; múltiplos rascunhos da mesma tag são recusados como ambiguidade. Releases estáveis já publicadas são tratadas como concluídas, sem reconstruir/substituir assets. Um novo dispatch em `main` pode completar somente a sincronização pendente de `develop`.

Para executar novamente, use **Actions → Release main e develop → Run workflow** e selecione `main` ou `develop`. `expected_sha` é opcional para execução manual e obrigatório no dispatch gerado pela sincronização. Um SHA divergente é descartado; nunca é usado para retroceder a branch. Uma repetição da mesma execução reconhece seu próprio commit de versão pelos marcadores do run/commit e pode continuar enquanto ninguém avançou o head.

`GITHUB_TOKEN` não recebe permissão `Workflows: write`. Algumas operações sobre alvos cujos workflows diferem da branch padrão podem ser recusadas pelo GitHub; a automação informa a restrição e não tenta contorná-la. Atualizações dos próprios workflows devem ser realizadas por quem possui a permissão apropriada, mantendo as branches coerentes.

## Arquivos de cada release

O prefixo de todos os assets é `EscrituraIntegrada-{version}-`.

| Sufixo | Conteúdo |
|---|---|
| `windows-x64.zip` | Pasta portátil com executável gráfico, runtime, frontend e avisos de terceiros |
| `source.zip` | `git archive` do SHA testado, com fontes e scripts correspondentes |
| `production-deploy.zip` | Compose, `.env` sem senha padrão, manifest de imagens e instruções do ambiente de produção |
| `develop-deploy.zip` | Ambiente independente, com projeto/porta/volume distintos |
| `linux-amd64-images.tar.gz` | Imagens para `docker load`, com relatório de recarga e smoke |
| `images.json` | Repositórios, tags, digests, IDs, origem e resultado da sonda de visibilidade |
| `linux-checks.json`, `windows-build.json`, `windows-smoke.json`, `windows-smoke.png` | Evidências dos gates; logs e relatórios auxiliares também acompanham a entrega |
| `manifest.json` | Commit, versão, execução, plataformas, gates e inventário com tamanho/SHA-256 |
| `SHA256SUMS.txt` | Hashes de todos os assets, inclusive do manifest, exceto o próprio arquivo de checksums |

O pacote de fontes lê somente blobs rastreados no commit; arquivos locais, credenciais, bancos e resultados não rastreados não entram no ZIP. A montagem rejeita arquivos vazios e arquivos com 2 GiB ou mais, em conformidade com o limite por asset do GitHub. Os uploads são feitos em streaming, sem carregar o bundle inteiro em memória.

## GHCR e equivalência de runtime

As seis imagens pertencem a `ghcr.io/codisplanfiscalai/escritura-integrada` e aos sufixos `-base`, `-redis`, `-postgres`, `-mysql` e `-minio`. O app usa a SemVer; base/serviços usam versões e identificadores derivados do conteúdo e dos upstreams fixados no catálogo. A imagem principal e o Windows compartilham as versões do backend no `docker/runtime.lock`. A segunda instalação de dependências de teste/desktop usa constraints sem hashes derivadas desse lock, preservando marcadores específicos do Windows.

A publicação autenticada no GHCR não muda automaticamente a visibilidade de um package. `public_pullable=false` não invalida um binário ou uma imagem autenticada já conferida: o manifest registra a condição e o deploy orienta autenticação, ajuste de visibilidade pelo proprietário ou uso do bundle offline. Não há chamada de API inventada para tornar packages públicos.

O backend permanece em SQLite. Redis, PostgreSQL, MySQL e MinIO são perfis opcionais de infraestrutura, com testes de inicialização e credenciais; ativá-los não implementa integração nem migra o banco da aplicação. Os gates de distribuição também não homologam regras fiscais, declarações SPED ou integração Prosoft. O README e a documentação funcional delimitam essas capacidades.

## Reaproveitamento de imagens e dependências

`build_images.py validate` consulta somente as tags derivadas dos inputs da base/serviços. O digest é resolvido e conferido contra os bytes do manifesto; o pull usa `repository@sha256`, nunca `latest`/`develop`. A plataforma e o content ID completo devem coincidir. Cache ausente/inacessível permite construir normalmente, sem mascarar falhas de construção/smoke; manifesto/identidade divergente bloqueia. O app de PR é sempre construído para seu SHA/versão. Não há login nem push GHCR em PR.

Base, upstreams e dependências usam o catálogo e `runtime.lock` fixados; alteração da base invalida app e MinIO. O content ID do app cobre recursivamente as fontes SPED e demais arquivos de app efetivamente copiados pelo contexto, incluindo dados JSON e catálogos de auditoria, além do frontend; ignora bytecode e os arquivos excluídos pela política de segurança do contexto. pip/npm mantêm os caches existentes e a chave npm normalizada ignora apenas a SemVer do projeto. BuildKit conserva seu cache de camadas dentro do daemon de cada runner; não adicionamos um exporter externo `gha` ao driver Docker sem o image store containerd exigido pelo Docker. Reutilizar imagens imutáveis prontas evita reconstruir suas dependências entre runners.

Em release, o job Docker salva as seis imagens **somente após** smoke aprovado, em `release-image-handoff` (retenção de dois dias). A exportação usa gzip nível 1, sem comprimir novamente no upload. O job publish baixa exclusivamente o artefato do próprio run (sem `run-id` externo) e recusa SHA/versão/canal/catálogo/inputs/plataforma/run/tentativa/hash/tamanho divergentes, tags extras e configurações inválidas **antes de carregar/push**. IDs carregados são conferidos novamente. Handoff ausente ou inválido falha; o workflow não recompila silenciosamente. O publicador ainda verifica tags existentes sem sobrescrevê-las, repete smokes e pulls por digest; a distribuição completa também repete a carga/smoke offline. Artefatos de PR nunca são fonte de publicação. O bloqueio de head superado continua antes da publicação e na confirmação/promoção; imagens versionadas que já tenham sido enviadas não autorizam promover um commit superado.

A transferência possui custo de serialização/armazenamento/rede e não é um cache global nem substitui os gates. Não se reaproveita binário/app final entre commits distintos; versão/SHA continuam exatos. Não houve atualização de dependências ou alteração dos templates bind.

## Retenção automática de caches

`python -m scripts.ci.cleanup_actions` apresenta o plano; `--execute --max-delete 100` exclui no máximo cem IDs por rodada. Acionamento manual começa em simulação. Há execução automática diária pela branch padrão e após cada execução de release confiável, inclusive develop depois que esta melhoria estiver integrada. Os dois caminhos compartilham `escritura-cache-cleanup`, sem cancelamento concorrente; a limpeza não ocupa a fila de mutações de release. Somente o job de limpeza recebe `actions:write` e leitura de PRs; os jobs de PR mantêm permissões de leitura.

- Preserva refs com workflows ativos/em fila e refs de PRs abertas, mesmo durante revisão sem runner ativo.
- Preserva duas variantes mais recentemente acessadas por família/OS/runtime em main e develop; variantes extras vencem após 30 e 14 dias, respectivamente. Tags estáveis são preservadas.
- Caches de PR fechada vencem após sete dias sem acesso; outras refs após trinta dias.
- Datas desconhecidas e associação de PR desconhecida em execução ativa são protegidas. Falha de leitura interrompe a limpeza.
- Antes de **cada** DELETE, refaz inventário/atividade/PRs e compara ID, ref, chave, versão, criação, tamanho e acesso. Cache restaurado/substituído ou nova atividade invalida a exclusão. A API não oferece transação com início de runner: resta uma pequena janela entre última leitura e DELETE, limitada pela retenção conservadora e serialização dos limpadores.
- DELETE usa exclusivamente `/actions/caches/{id}`, sem retry, inclusive quando o resultado é incerto. Registra IDs removidos/preservados/erros no artefato de relatório. Não executa prune Docker nem altera artefatos Actions de release, releases/assets, tags, GHCR ou dados da aplicação.

Retenção de artefatos temporários Actions (incluindo o handoff de dois dias) e assets de release são independentes dos caches de dependências. Para testar a política sem token, execute `PYTHONPATH=tests:. python -m unittest test_ci_artifacts_cache test_ci_delivery_cache -v`; todos os dados desses testes são sintéticos.

## Baseline e limites de medição

A [release develop 43812084887](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43812084887), anterior à melhoria, concluiu em 51m31s. Tempos observados de jobs: Linux 9m22s; Windows 30m28s; macOS arm64 5m43s; macOS x64 10m; Docker 5m44s; publicação 10m10s. Dentro deles, build/smoke macOS: 292s/503s; Windows app: 269s, instalador: 272s; construir/validar imagens: 336s; publicar imagens: 216s; exportar/provar carga offline: 261s. São tempos de uma execução e seus runners/filas, não estimativa de economia.

Testes de composição sintéticos demonstram seis comandos build em validate sem cache, um com as cinco imagens auxiliares reutilizáveis e zero reconstruções em publish com handoff válido, mantendo o smoke em todos os caminhos. Medir a próxima release confiável por versão/SHA/run (tempos por imagem registrados no manifesto), custo/tamanho da transferência e tempo total é necessário para quantificar ganho real. Uma PR de leitura não exercita publicação nem os gates nativos de main durante a pausa; não comprova redução de tempo em release estável.

## Referências oficiais

- [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html).
- [Concorrência e filas do GitHub Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
- [Eventos disparados com GITHUB_TOKEN](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
- [REST: workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).
- [REST: releases e permissões](https://docs.github.com/en/rest/releases/releases).
- [REST: upload e digest dos assets](https://docs.github.com/en/rest/releases/assets).
- [Limites dos assets de releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
- [REST: caches Actions](https://docs.github.com/en/rest/actions/cache).
- [Docker: backends de cache e requisito containerd do driver Docker](https://docs.docker.com/build/cache/backends/).
- [Autenticação e visibilidade do Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Fluxos no navegador

Os jobs Linux de PR e release executam `scripts/smoke_browser.py` com Chromium/Playwright 1.62.0, depois dos testes Python, testes de datas e build Vue. O cenário usa exclusivamente dados fictícios, com consulta CNPJ simulada e declarada no relatório. Percorre edição sem ativação indevida, cadastro assistido, documento → títulos/contabilidade, baixa/estorno, importação e relatório. Verifica transbordamento nas larguras 1440, 1024 e 390. Capturas e JSON ficam no artefato `browser-evidence`, inclusive em falha, por 14 dias. Esse gate não comprova disponibilidade dos provedores externos nem homologação tributária.

A release também recebe `EscrituraIntegrada-<versão>-browser-evidence.zip`, com relatório e capturas. A montagem verifica aprovação, versão e commit, oito verificações concluídas e presença das imagens; o pacote integra o manifesto de hashes da distribuição.
