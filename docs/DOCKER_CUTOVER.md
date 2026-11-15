# Corte Docker opcional, com dados congelados

Continuação da preparação da [PR45](https://github.com/codisplanfiscalai/escritura-integrada/pull/45), encadeada sobre ela. Não instala executor, não altera a stack/VPS, não publica imagem/release e não toca dados reais. O padrão continua **somente consultar/preparar**. Código e provas descartáveis não constituem homologação de uma instalação.

## Autoridade e pré-requisitos

O administrador precisa primeiro revisar e autorizar a [instalação do executor](DOCKER_UPDATER.md#instalação-adicional-ainda-pendente). O app permanece UID/GID 10001:10001, sem Docker socket, grupo Docker ou root. O executor do host possui autoridade Docker relevante: o RPC limita ações, mas sua conta não é uma sandbox contra comprometimento do próprio executor. Scripts/configuração devem ser inacessíveis para escrita pelo app. Não existe instalador ou serviço habilitado automaticamente.

Para habilitar corte, acrescente **explicitamente** `--enable-cutover --exclusive-data-writer` ao comando de host. Essa declaração e a confirmação na interface exigem janela exclusiva: suspenda operadores Dockge/Compose, tarefas do host e outros escritores. O lease do executor não bloqueia root/outro operador Docker. Ele detecta containers em execução com binds RW sobrepostos, inclusive um Dockge com acesso ao diretório pai; nesse caso recusa o corte. Um escritor externo pode aparecer após a verificação: exclusividade administrativa continua sendo requisito. Não habilite o recurso enquanto essa condição não puder ser garantida.

Escopo deliberadamente restrito: Linux amd64, Docker Engine API >=1.45, daemon/socket local, bind existente exato `./data/app:/data` (ou origem relativa explicitamente configurada), usuário 10001:10001, comando padrão `python scripts/run_container.py`, apenas `/data` gravável. Preserva mounts RO, env, portas fixas, redes/aliases, labels e opções de host. Named volumes, mounts RW adicionais, IP estático, portas dinâmicas, entrypoint/comando customizado, SIGKILL, rede host/container, privileged, auto-remove e volumes-from são recusados. Restart policy aceita `no` ou `unless-stopped`; `always`/`on-failure` são recusadas porque o container antigo é retido parado e não pode voltar a escrever após reinício do daemon. Veja a [semântica oficial de restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/).

**Ambas as imagens precisam conter este protocolo.** Uma instalação antiga sem `app.update_guard` é recusada antes de parar qualquer container. A primeira instalação dessa versão exige bootstrap administrativo separado e autorizado. A igualdade conservadora do ABI inclui código de inicialização/migração e o esquema de uma base sintética nova das duas imagens. Esquema real 6, integridade e FKs são verificados; índices já existentes permanecem. Alteração de ABI/esquema exige fluxo separado, sem checkbox de exceção. Não executa migração de banco nem PostgreSQL.

## Sequência verificável

1. O admin consulta/prepara um digest no canal escolhido; o corte recebe somente o ID persistente dessa preparação e chave de intenção. Reconfere container, imagem/digest em cache, montagem, configuração, espaço e contrato. Nunca resolve novamente o alias para selecionar outro alvo. O Engine cria pelo ID de configuração previamente conferido contra o digest. Arquivos Compose/.env não são reescritos: um redeploy posterior pelo Dockge/Compose pode resolver novamente o alias declarativo. Cabe ao administrador conciliar a referência desejada em sua configuração, em operação separada; não há troca silenciosa de canal ou alteração de arquivos de configuração pelo executor.
2. Publica atomicamente marcador privado em `/data`, pertencente ao job, com ABI/esquema. A API bloqueia novas operações de negócio, login/setup e novas transações. Solicitações admitidas antes do marcador podem terminar suas transações. Saúde, sessão e controle administrativo continuam legíveis. Não inicia workers/limpeza no alvo enquanto o marcador existir. A indisponibilidade começa aqui e inclui o backup inteiro; não há promessa de duração curta para bases grandes.
3. Confirma saúde da origem em manutenção e pede encerramento controlado `stop?t=-1`. Não escala para SIGKILL: timeout da conexão gera recuperação necessária e o encerramento pode continuar. Só prossegue após ExitCode 0, sem OOM, processo parado e nenhuma outra montagem escritora. Não copia SQLite em uso.
4. Faz inventário de arquivos/modos/UID/GID/mtime/hardlinks e SHA-256, com limite de 50 mil entradas. Recusa symlinks, arquivos especiais e propriedade divergente; não faz chown. Verifica espaço do destino (2× bytes +256 MiB), copia a árvore congelada e cria também backup SQLite pela API de backup, com integrity/FK/schema checks. Compara inventários da origem e cópia, fsync e receipt. Helper usa UID 10001, source RO, rede/capabilities ausentes, rootfs RO, memória/CPU/PIDs limitados; timeout de dez minutos. O diretório novo de destino é gravável pelo helper, dentro de pai privado 0700 do executor. Nenhum backup anterior é sobrescrito/apagado.
5. Retém a configuração original no ledger privado e o container antigo parado. Renomeia-o, cria o único app com a imagem conferida e configuração preservada; compara Config/HostConfig/rede reais antes de iniciar. Normaliza somente o default equivalente `OomKillDisable=null/false`; alterações explícitas continuam sendo recusadas. Nenhum volume é removido.
6. Exige Docker **healthy** e HTTP real `/api/health`, versão, protocolo e mesmo marcador. Reconfere configuração, esquema e inventário congelado. Persiste o ponto de liberação antes de retirar o marcador. Testa `BEGIN IMMEDIATE/ROLLBACK` e saúde HTTP/healthcheck sem manutenção. Só então `completed` e `application_updated=true`. `prepared` continua sendo apenas download verificado.

Backups completos, Env/configuração e caminhos ficam exclusivamente em `.docker-updater` privado, nunca no socket montado, Git, log público ou artefato CI. O resultado público contém versões/digests/IDs e receipt com hashes/contagem/bytes, sem nomes de arquivos/configuração. A árvore original `./data/app`, UID e demais mounts permanecem. PR35 e seus scripts/override não são copiados ou alterados.

## Interrupção e recuperação explícita

Um só pull/corte ativo, lease do processo, índices únicos no ledger e worker serializado. Mesma intenção não repete o corte; preparação já consumida não corta de novo. Limite de 100 cortes retidos, além dos limites de consulta/preparação. Uma falha após início da manutenção fica em `recovery_required`, sem retry/rollback automático. Reiniciar o executor apenas registra essa condição. Nunca exclui container, volume, dado, backup ou histórico para liberar limite.

Se a interface estiver disponível, admin pode solicitar **Conferir/liberar alvo** ou **Solicitar imagem anterior**. Se não voltar, o dono do executor pode usar o canal local (mesmo socket/lease, sem acesso web):

```sh
python /caminho/revisado/docker_update_control.py --project-directory /caminho/da/stack status
python /caminho/revisado/docker_update_control.py --project-directory /caminho/da/stack reconcile-target --cutover-id ID_HEXADECIMAL_DO_JOB
# Somente antes da liberação de escritas e com dados/esquema congelados:
python /caminho/revisado/docker_update_control.py --project-directory /caminho/da/stack recover-previous --cutover-id ID_HEXADECIMAL_DO_JOB
```

O UID do dono só é admitido no socket quando corte foi explicitamente habilitado. A aplicação não pode forjar o ator `host`. Diretório de socket owner executor, sem escrita por grupo/outros; socket 0660 e `SO_PEERCRED` continuam necessários. Consulte `--help` para a ordem dos argumentos; nenhum comando aceita imagem, shell, serviço ou origem arbitrária via RPC.

Resposta incerta ao criar container é conciliada pelo nome esperado **e nonce do job, imagem e configuração exatas**, sem adotar container alheio. Retomada de criação exige backup verificado e dados ainda congelados. Retorno à imagem anterior usa a mesma árvore, apenas se ABI/esquema e fingerprint não mudaram, sem restauração de backup. O alvo malsucedido também fica retido parado. Após persistir intenção de liberar escritas no alvo, retorno à imagem antiga é proibido, inclusive se uma resposta se perdeu. Conciliar o alvo nesse estado preserva novas gravações e verifica sua saúde; não compara/restaura snapshot antigo quando o marcador já foi removido. Se a intenção de liberação foi persistida mas o mesmo marcador continua intacto, a retomada verifica contrato/fingerprint congelado antes de repetir sua remoção. Marcador alheio ou dados divergentes bloqueiam a liberação. Mudança de dados/esquema, marcador ausente/alheio, configuração externa ou interrupção não comprovadamente limpa pode exigir recuperação assistida. Não promete rollback sem perda.

## Provas reproduzíveis e limites

```sh
PYTHONPATH=tests:scripts:. python -m unittest test_docker_updates test_docker_cutover -v
node --test frontend/tests/*.test.js
(cd frontend && npm ci && npm run build)
# Somente Docker Linux descartável, Chromium e dados sintéticos:
ESCRITURA_TEST_BROWSER=/usr/bin/chromium python scripts/smoke_docker_cutover.py --browser
```

O smoke constrói imagens **locais sintéticas** sobre base publicada fixada por digest; não publica imagens e os receipts de registro são fixtures. Docker Engine, containers UID 10001, bind relativo, socket entre app/executor, backup, HTTP, healthcheck, interface e recuperação são reais. Inclui contrato incompatível, escritor sobreposto, falha de backup, alvo sem saúde, perda da resposta de criação/reinício do executor e interrupção antes de remover o marcador, solicitação em andamento drenada, corte concluído, sessão/empresa/índice/arquivo preservados, gravações após liberação e bloqueio de retorno quando dados mudam. Não equivale a upgrade entre duas releases publicadas nem a homologação do VPS, SELinux/userns, disco cheio real ou falha física de energia. Relatórios/capturas contêm apenas fixtures. Backups/ledger privados nunca são enviados como artefato.

Ainda pendentes: revisão do administrador, instalação e concessão de autoridade no host, bootstrap de origem compatível, comprovação de exclusividade da stack concreta e homologação em Docker da instalação autorizada. Nada disso foi realizado pelo desenvolvimento/PR.
