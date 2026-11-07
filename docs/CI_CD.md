# Integração, versões e distribuição

O repositório usa `main` para versões estáveis e `develop` para uma pré-release contínua. A aplicação, o executável Windows e a imagem principal recebem a mesma SemVer. O fluxo publica somente depois dos gates Linux, Windows empacotado e Docker. A existência destes arquivos de automação, por si só, não comprova que uma execução remota terminou: os resultados são registrados nos jobs, nos relatórios e no manifest de cada release.

## Workflows e permissões

| Arquivo | Disparo | Resultado | Permissões de escrita |
|---|---|---|---|
| `ci.yml` | PR para `main` ou `develop` | Testes, frontend, pacote Windows e validação das seis imagens, sem publicação | Nenhuma permissão de escrita no repositório ou no GHCR |
| `release.yml` | Push em `main`/`develop` ou execução manual | Commit de versão, gates, GHCR, bundles, release e sincronização de `develop` após `main` | `contents: write` nos jobs que alteram refs/releases; `packages: write` somente em publicação; `actions: write` somente para dispatch |
| `cache-cleanup.yml` | Domingo às 04:23 UTC ou execução manual em `main` | Plano ou exclusão limitada de caches elegíveis, com relatório | `actions: write`; não exclui releases |

As actions externas estão fixadas por SHA, com a versão correspondente em comentário. Os runners são `ubuntu-24.04` e `windows-2022`; a construção usa Python 3.12 e Node.js 24. PRs usam `pull_request`, sem credenciais de publicação. Não há `pull_request_target` executando código do autor com token de escrita.

## Política SemVer

| Situação | Exemplo | Comportamento |
|---|---|---|
| Primeira versão estável | `0.4.0` | Tag `v0.4.0`, release estável e assets com `0.4.0` |
| Desenvolvimento posterior | `0.4.1-dev.12` | Release e tag móveis `develop`; título e arquivos identificam a SemVer completa |
| Promoção de desenvolvimento | `0.4.1` | O sufixo é retirado em `main`, gerando nova tag estável |
| Novo código com versão já reservada | `0.4.1` → `0.4.2` | Incrementa patch; não reutiliza uma tag para outro commit |
| Incremento explícito maior | `0.5.0-dev.20` | Preserva o novo major/minor quando superior à linha estável |
| Conferência de PR | `0.4.1-pr.7.15` | Carimbo apenas no checkout temporário; sem commit, tag ou publicação |

`github.run_number` fornece o último componente de `-dev.N`. A base de `develop` é pelo menos o próximo patch da versão de `main` e das tags estáveis já reservadas. Não são criadas tags para cada `-dev.N`: existe um único marcador `develop`. O ZIP de fontes e o manifest fixam o commit de cada entrega, pois o marcador muda.

O script grava `VERSION`, `app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json` e `package.json`; sincroniza também `package-lock.json` da raiz caso exista. Ele modifica somente a versão do projeto, incluindo a entrada raiz de `packages` no lock. Preserva scripts de construção e versões das dependências. A interface lê a versão do manifest do frontend.

Depois da publicação estável, a sincronização integra `main` em `develop`, prepara uma versão superior e dispara explicitamente o próximo pipeline. Entre o início dessa transição e a conclusão dos novos gates, a pré-release anterior continua disponível; o marcador é atualizado apenas quando a nova distribuição foi conferida.

## Sequência de publicação

1. **Preparar:** verifica que o evento ainda representa o head da branch, calcula a SemVer e cria somente o commit dos manifests que mudaram. O head avança sem `force`. A execução registra o SHA resultante no plano `ci-plan.json`.
2. **Linux:** confere todos os manifests, instala o runtime pelo lock com hashes, compila a interface e seus avisos de terceiros, executa os testes de dia civil do frontend, a suite Python e a compilação sintática. O frontend distribuído ao Windows sai deste job.
3. **Windows:** repete a suite Python com o runtime comum, confere a ausência de alterações rastreadas e gera o pacote x64. O smoke extrai o ZIP em caminho com espaços/Unicode, abre o executável gráfico, verifica a área de trabalho renderizada, versão/API e encerramento. Processos remanescentes ou encerramento forçado reprovam o gate. JSON, captura e logs ficam nos artefatos da execução.
4. **Docker:** constrói e testa localmente as seis imagens `linux/amd64`, sem login/push. Valida a aplicação e os perfis opcionais, inclusive os arquivos Compose reais. O builder `default`, com driver Docker, permite resolver a base local nesta etapa.
5. **Reservar e publicar:** após os três gates e nova checagem do SHA, reserva a tag estável imutável, quando aplicável, e autentica no GHCR. Publica/reutiliza imagens por identidade e digest, testa as imagens exatas e verifica pull autenticado. Uma sonda anônima registra `public_pullable` separadamente.
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

## Retenção de caches

O script `python -m scripts.ci.cleanup_actions` apresenta o plano sem excluir. `--execute` autoriza a execução do plano e `--max-delete 100` limita a quantidade por rodada. A agenda semanal já usa a opção de execução; o acionamento manual começa em simulação.

- Preserva caches de `main` e de tags estáveis, assim como refs com execuções ativas.
- Mantém duas variantes recentes por família de cache em `develop`; as demais vencem após 14 dias sem acesso.
- Caches de PR vencem após 7 dias; outras refs após 30 dias.
- Datas desconhecidas são preservadas. A atividade e a lista de caches são consultadas novamente antes da exclusão por ID.
- O script não apaga releases, tags, imagens GHCR ou dados da aplicação. Assets antigos da pré-release são tratados somente após uma nova publicação aprovada do marcador `develop`.

A chave npm ignora a versão do projeto e considera o lock de dependências; uma nova SemVer não cria desnecessariamente outro cache de pacotes. A retenção de artefatos temporários Actions é de 7–30 dias conforme sua finalidade. Assets publicados em releases têm ciclo de vida independente.

## Referências oficiais

- [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html).
- [Concorrência e filas do GitHub Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
- [Eventos disparados com GITHUB_TOKEN](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
- [REST: workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).
- [REST: releases e permissões](https://docs.github.com/en/rest/releases/releases).
- [REST: upload e digest dos assets](https://docs.github.com/en/rest/releases/assets).
- [Limites dos assets de releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
- [REST: caches Actions](https://docs.github.com/en/rest/actions/cache).
- [Autenticação e visibilidade do Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Fluxos no navegador

Os jobs Linux de PR e release executam `scripts/smoke_browser.py` com Chromium/Playwright 1.62.0, depois dos testes Python, testes de datas e build Vue. O cenário usa exclusivamente dados fictícios, com consulta CNPJ simulada e declarada no relatório. Percorre edição sem ativação indevida, cadastro assistido, documento → títulos/contabilidade, baixa/estorno, importação e relatório. Verifica transbordamento nas larguras 1440, 1024 e 390. Capturas e JSON ficam no artefato `browser-evidence`, inclusive em falha, por 14 dias. Esse gate não comprova disponibilidade dos provedores externos nem homologação tributária.
