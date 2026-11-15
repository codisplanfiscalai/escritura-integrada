# Preparação de atualização Docker pela interface

Incremento sobre develop `955404e6b504f809514e9ead3c54ed62b258df56` (0.9.0-dev.12). **Consultar e baixar uma imagem funciona quando o executor externo está instalado e autorizado; substituir a aplicação ainda não está implementado.** A interface diz isso antes da confirmação e em cada resultado. Não existe endpoint de corte, recriação, backup, migração ou rollback, nem sucesso fictício de atualização.

## Escopo e separação de autoridade

- **Sistema → Atualização Docker**, exclusivo do administrador e utilizável sem empresa ativa. A API exige sessão ativa, perfil admin vigente e CSRF/origem nas mutações. Demonstração não executa operações.
- `app/docker_updates.py` conversa somente com o socket Unix configurado pelo administrador em `ESCRITURA_UPDATE_SOCKET`. A aplicação continua UID/GID 10001:10001; não recebe socket Docker, grupo Docker ou root. Ausência/falha do executor é indisponibilidade explícita.
- `scripts/docker_update_executor.py` é um programa opcional de host Linux, separado do app. Usa Python 3.10+, Docker CLI/Buildx e exclusivamente `unix:///var/run/docker.sock`. Não usa shell nem comandos, imagens, serviços ou caminhos recebidos do navegador. Sua conta precisa da autoridade Docker no host; essa concessão é relevante e **não foi feita por esta PR**. A instalação deve ser deliberada, com código revisado e inacessível para escrita pelo app.
- O protocolo aceita apenas `status`, `check(channel)` e `prepare(plan_id,idempotency_key,actor)`. `SO_PEERCRED` restringe o UID cliente. O diretório de socket é a única pasta compartilhada com o app, somente leitura. O ledger privado fica fora dessa montagem.
- O repositório da imagem é constante: `ghcr.io/codisplanfiscalai/escritura-integrada`. Canais aceitos: `develop` (pré-release) e `latest` (main estável). A seleção só consulta/prepara o canal escolhido: não altera `.env`, Compose, aliases ou releases. `latest` recusa versão com pré-release/metadados. Não promove develop para estável.

## O que acontece em cada operação

1. **Consultar alvo** identifica exatamente um app em execução pelos labels Compose do projeto configurado no host. Confere a montagem bind `/data`, origem exata já existente dentro do projeto, RW, plataforma Linux amd64 e UID/GID 10001:10001. Named volumes, outro bind, root ou origem não comprovada são recusados; não prepara pastas nem migra arquivos.
2. Resolve o canal no registro com Buildx, fixa o digest remoto, verifica SHA-256 dos bytes do manifesto e, se houver índice, seleciona o único manifesto Linux amd64. Consulta versão, revisão, origem e UID da configuração por referência imutável. A interface mostra versão/digest instalada e alvo antes da confirmação. Labels não são uma assinatura independente: a confiança inclui TLS/GHCR, repositório fixo e administração dos aliases publicados.
3. Guarda snapshot com TTL de cinco minutos: container, ID/digest anterior, versão, alvo e hash de configuração/mounts. O hash cobre env/HostConfig/mounts; seus conteúdos e caminhos não saem do executor. Não captura bancos, documentos, backups ou credenciais.
4. **Baixar imagem por digest** registra o job em SQLite privado antes de responder. Revalida a instalação/configuração e o mesmo canal/digest antes do pull. Se o canal avançou antes dessa revalidação, exige nova consulta/confirmação. Se avançar depois, o download continua preso ao digest aprovado; não seleciona silenciosamente outro alvo.
5. Confere espaço no filesystem Docker (mínimo indicativo de 2 GiB; o download pode exigir mais). No Docker rootless, se o diretório privado não puder ser percorrido, consulta o mountpoint correspondente em `/proc/self/mountinfo` e usa `statvfs` ali. Isso exige executor **no próprio host e namespace de mounts do daemon**, sem socket encaminhado/daemon remoto; não abre, monta ou altera o conteúdo de armazenamento Docker. Execute a homologação dessa condição antes de instalar.
6. Executa apenas `docker pull --platform linux/amd64 <repositório>@sha256:...`, com prazo de dez minutos. Confere ID da configuração, RepoDigest, plataforma, UID/GID, origem, versão e commit. Revalida que a instalação original não mudou. Resultado `prepared` significa **imagem em cache verificada**, sempre com `application_updated=false` e `cutover_supported=false`. Não chama `up`, `restart`, `stop`, `rm`, `prune`, backup, migração ou restauração.

A aplicação e os dados continuam em uso durante o download. Não há manutenção global neste incremento porque não há corte. Nenhum backup é anunciado como realizado. Healthcheck/HTTP do alvo ainda não podem ser comprovados sem iniciar essa imagem, o que fica fora do executor atual.

## Concorrência, persistência e recuperação

Estados: `queued → pulling → validating → prepared`, ou `failed`; operações ativas encontradas no reinício viram `interrupted`. O estado representa fases, sem porcentagem de download inventada. O histórico exibe as dez solicitações mais recentes, com ID do ator administrativo, timestamps, snapshot anterior e alvo.

Existe uma só operação ativa, com índice único no ledger e lease `flock` no processo do host. Mesma chave/corpo retorna o mesmo job; outra intenção com a mesma chave é 409; um snapshot não agenda dois pulls mesmo com outra chave. A interface impede cliques simultâneos e conserva a intenção para repetição após erro de transporte. Desativar/desmontar a tela invalida respostas antigas e interrompe polling; reabrir consulta o histórico persistente. Polling só ocorre enquanto há preparação em andamento.

Limites: 12 consultas de canal/hora (inclusive consultas que falharam), seis preparações/hora, 200 jobs conservados, TTL de cinco minutos, entrada do socket de 4 KiB e resposta web de 64 KiB. Ao atingir o histórico, novas operações são recusadas; arquivamento do ledger exige procedimento administrativo separado. Não apaga histórico automaticamente. O servidor serializa admissões; pull roda em um worker independente. O polling pode esperar uma consulta em curso; erros de transporte são apresentados como resultado pendente/indisponível.

Falhas de rede/auth, pouco espaço, digest/UID incorretos e instalação alterada falham sem corte. Timeout pode deixar camadas baixadas pelo daemon: o resultado não vira sucesso. Queda após persistir ou terminar o pull preserva o registro e não dispara nova operação automaticamente. Verifique cache/estado antes de uma nova consulta e confirmação. Repetir a intenção original não reexecuta jobs terminais. Nenhuma recuperação remove imagem anterior, dados, volumes ou backups.

## Instalação adicional, ainda pendente

**Nada desta seção foi aplicado ao VPS/Dockge.** A configuração padrão permanece desativada, sem novos serviços ou mounts nos templates. Não há instalador automático ou inicialização silenciosa.

Após autorização do administrador, homologue primeiro em stack descartável:

1. Instale uma cópia revisada do executor no host, com conta própria autorizada para Docker local. Restrinja a escrita do script/configuração à administração. Confirme plataforma, Buildx, credenciais GHCR de leitura quando necessárias, filesystem Docker, UID e mapeamentos do Docker rootless/userns.
2. No diretório da stack, prepare `.docker-updater` de propriedade do executor com modo 0700. Prepare `.docker-updater/run` real, sem symlink, com owner executor, grupo compartilhado explicitamente escolhido e modo 2750. O socket herda esse grupo e tem modo 0660. O ledger/lease continuam no pai privado 0700, não acessível ao cliente.
3. Inicie explicitamente, por mecanismo de supervisão escolhido pelo administrador:

   ```sh
   python /caminho/revisado/docker_update_executor.py \
     --project-directory /caminho/da/stack \
     --project-name escritura-develop \
     --app-data-bind ./data/app \
     --allowed-uid 10001
   ```

   `--allowed-uid` é o UID real observado no host por `SO_PEERCRED`. Docker rootless/userns pode mapear o UID 10001 do container para outro UID no host: confirme o mapeamento e o grupo do socket em homologação, sem aumentar privilégios do app. O executor não faz chown/chmod na pasta existente de dados.
4. Somente depois de revisar a instalação, acrescente ao serviço app **apenas** a variável e montagem do socket. Exemplo de trecho a incorporar, conservando todas as outras configurações/mounts:

   ```yaml
   environment:
     ESCRITURA_UPDATE_SOCKET: /run/escritura-update/control.sock
   volumes:
     - type: bind
       source: ./.docker-updater/run
       target: /run/escritura-update
       read_only: true
       bind:
         create_host_path: false
   ```

   A nova origem é relativa à stack. **Não substitua a lista existente de volumes por este trecho.** Mantenha exatamente o atual `./data/app:/data`, usuário e demais opções. Essa alteração da stack exige a autorização de instalação que está pendente e não deve ser feita enquanto uma atualização estiver em andamento. Não monte o ledger, o diretório pai ou `/var/run/docker.sock` no app.
5. Confirme que o cliente autorizado conecta, UID estranho é recusado, o app não consegue editar o socket/ledger nem acessar Docker, a versão/digest instalada está correta e um pull sintético deixa o container, montagem e dados intactos. Valide SELinux, userns e filesystem da instalação concreta. Uma indisponibilidade de executor não autoriza afrouxar essas restrições.

A PR35 continua independente. Este incremento não copia `deploy_storage.py`, não altera templates/overrides de armazenamento e não depende de sua integração. O host config aponta ao bind que **já existe**; para o VPS descrito é `./data/app`. Quando a #35 for integrada, mantenha seu override de instalação existente e `ESCRITURA_APP_DATA_BIND=./data/app`; não use este recurso para migração ou troca de origem.

## O que falta para atualizar de fato

Um próximo incremento precisa implementar e homologar, antes de expor uma confirmação de corte:

- lease contra check/pull/recreate concorrentes, incluindo outro operador do Dockge;
- encerramento controlado e janela breve sem escritas de **todos** os escritores relevantes; trava atual não existe;
- espaço suficiente e backup consistente de banco/arquivos/configuração, verificado e privado, preservando dados e backups existentes;
- compatibilidade explicitamente comprovada para esquema/dados e plano que não execute migrações automaticamente como efeito deste recurso;
- recriação estrita do único app por digest aprovado, preservando mounts, env, secrets, redes, portas, usuário, labels e opções, sem imprimir Compose renderizado com segredos;
- confirmação do digest/versão realmente em execução, **healthcheck e resposta HTTP do app**, prazo e estado de recuperação verificável;
- tratamento de falhas de backup/saúde/corte/interrupção. Rollback de imagem só com compatibilidade comprovada. Gravações novas não podem ser substituídas por backup antigo. Esquema incompatível exige recuperação assistida; não prometer reversão sem perda.

Os testes que recusam backup/health/rollback validam a **ausência de autoridade** no protocolo atual; não são testes de um backup, atualização ou rollback implementado. Nenhuma operação foi executada no VPS ou em dados reais.

## Validação reproduzível

```sh
PYTHONPATH=tests:scripts:. python -m unittest test_docker_updates -v
node --test frontend/tests/*.test.js
(cd frontend && npm ci && npm run build)
python -m scripts.ci.checks --version "$(cat VERSION)" --source-sha "$(git rev-parse HEAD)"
# Opcional: baixa uma imagem publicada, usa apenas stack temporária e Chromium.
ESCRITURA_TEST_BROWSER=/usr/bin/chromium python scripts/smoke_docker_updates.py
```

O smoke é uma preparação real com GHCR/Docker/Unix socket e a interface local, para container publicado com bind sintético e UID 10001. O backend cliente do smoke roda como processo local autorizado, não dentro da imagem publicada; a montagem do socket dentro de um novo container e a imagem desta PR ainda precisam do gate Docker/homologação. Não instala serviço, não recria o app, não publica imagem e não substitui a homologação do VPS. Capturas/relatório locais em `artifacts/docker-updates/` contêm só fixtures e ficam fora do Git. O script remove somente seus containers e arquivos temporários.
