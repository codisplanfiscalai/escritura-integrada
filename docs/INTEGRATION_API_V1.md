# Integrações v1 — corte de centros de custo

Este documento registra o corte inicial do PR #69. A [expansão de domínios](INTEGRATION_DOMAINS_V1.md) acrescenta recursos e recuperação, preservando os contratos abaixo.

## Inventário e alcance

Base verificada: `develop` dev.40, `a31f717f3e037cc4e33fddabcdd2f6fc3f3ee5cc`.
`app/api.py` já oferecia `/api` de mesma origem, sessão, CSRF, ACL por empresa
 e exercício. Isso não era uma API externa nem entrega de eventos. A branch
`feat/integrations-postgres-validation` estava 200 commits atrás, sem delta
à frente de develop. Não havia AGENTS.md nem `.agents/skills` nesse checkout.
Foram lidos README, contrato HTTP, validação e gate de testes existente.

Este incremento implementa **somente centros de custo**:

| Fronteira | Implementado |
|---|---|
| API externa | Consulta paginada de centros de custo e histórico de eventos com Bearer |
| Gestão interna | Emitir/listar/revogar credenciais; criar/revogar destinos; consultar últimas 100 entregas |
| Eventos | Inclusão e atualização de centro de custo; outbox SQLite transacional |
| Webhooks | HTTPS, assinatura, fila persistida, retries finitos, auditoria, exemplo de inbox idempotente |
| WebSocket | Autenticação no primeiro frame, origem permitida, uma empresa, cursor, ACK, reconexão |

Não há API externa genérica de documentos, lançamentos, títulos, importações,
obrigações ou cadastros completos, nem mutações de domínio por Bearer. Não há
transmissão fiscal. Não é homologação de integrações de terceiros.

## Permissões e isolamento

Gestão usa as rotas `/api/companies/{cid}/integrations/...` e conserva sessão,
CSRF, empresa ativa e validação transacional existentes. A nova rotina
`system.integrations` tem `read`, `create`, `delete`, por empresa. Não exige
administração global. O usuário que emite precisa também de `read` **e** `export`
em `accounting.cost_centers`; a ação `export` passa a existir explicitamente.
Concessões e negações são configuráveis pelo cadastro de acessos já existente.

Cada credencial pertence a um usuário e a **uma única empresa**, com escopos
`cost-centers:read`, `events:read`, `webhooks:deliver` selecionados explicitamente.
Não aceita wildcard. Todas as leituras/entregas reavaliam usuário ativo,
permissões atuais (incluindo `system.integrations:create`), escopo, validade e
revogação. O token não herda a empresa ativa da sessão. O banco guarda somente
SHA-256 do token aleatório de 256 bits. O token é devolvido uma única vez.
Validade: 60 segundos a 30 dias; padrão um dia. Máximo 50 credenciais ativas por
empresa. Rotação: emitir outra, atualizar o cliente e revogar a anterior.

O modelo existente não tem uma entidade organização: a instalação/banco é a
fronteira organizacional. Empresas são isoladas dentro dela; credenciais de uma
instalação não autenticam em outra. Não oferece gestão SaaS multiorganização.
Centros de custo são cadastros da empresa, sem competência: não se inventa uma
restrição anual para esse domínio. Outros domínios precisarão de políticas próprias.

## Configuração

Instale as dependências fixadas, incluindo `websockets==16.0`. O lock Docker
inclui hashes dos wheels oficiais da mesma versão. Nenhum workflow foi alterado.
Os pontos Docker/desktop limitam frames recebidos a 2048 bytes, fila do protocolo
quando suportada a 4, desativam compressão e mantêm access logs desativados.
Na execução manual use:

```sh
python -m uvicorn app.api:app --host 127.0.0.1 --port 8765 \
  --ws-max-size 2048 --ws-max-queue 4 --no-ws-per-message-deflate --no-access-log
```

Variáveis, lidas no início do processo:

- `ESCRITURA_INTEGRATION_ORIGINS`: origens exatas separadas por vírgula, por exemplo
  `https://cliente.example.invalid`. Vazio bloqueia WebSocket.
- `ESCRITURA_WEBHOOK_DESTINATIONS`: mapa JSON de IDs de empresa para listas de URLs
  HTTPS exatas, por exemplo `{"1":["https://receptor.example.invalid/events"]}`.
  Ausente, vazio ou inválido bloqueia destinos. A allowlist é decisão do operador
  **por empresa**; uma permissão de empresa não autoriza novos hosts nem destinos de outra empresa.
- `ESCRITURA_WEBHOOK_KEY`: segredo aleatório com pelo menos 32 caracteres,
  fornecido por secret manager/ambiente protegido. Ausência bloqueia criação/entrega.
  Não usar as chaves sintéticas dos testes. Backup seguro fora do repositório.
- `ESCRITURA_DATA_DIR`: diretório persistente da instalação, já existente.

Use TLS no proxy da aplicação, encaminhe Upgrade/Connection para WebSocket e
configure timeout superior a 20 s. Não habilite logs de Authorization, cookies,
frames ou corpos; nunca coloque tokens em URL, query string ou subprotocolo.
Allowlist de origem não cria CORS: consulta externa HTTP destina-se a clientes
servidor; navegador pode usar o protocolo WebSocket descrito abaixo.

A chave de assinatura por destino é derivada por HMAC-SHA256 da chave mestra e
ID aleatório. É devolvida apenas ao criar o destino. Trocar a chave mestra muda
assinaturas de todos os destinos: revogar e recriar destinos com os consumidores
coordenados; não há rotação com duas chaves simultâneas neste corte.

## Contratos e sequência sintética

Em sessão autenticada, empresa 1 ativa, com `X-CSRF-Token` da sessão:

```http
POST /api/companies/1/integrations/credentials
Content-Type: application/json
X-CSRF-Token: <csrf-da-sessao>

{"scopes":["cost-centers:read","events:read","webhooks:deliver"],"expires_in":3600}
```

Resposta 201: `{id,token,expires_in,scopes}`. Guarde o token em secret manager.
`GET .../credentials` lista metadados (escopos serializados em JSON, sem hash/token).
`DELETE .../credentials/{id}` revoga de forma idempotente.

```http
GET /integrations/v1/companies/1/cost-centers?after=0&limit=100
Authorization: Bearer <token>
```

Resposta: `{"version":"1","items":[{"id":1,"code":"CC-SINTETICO","name":"Centro fictício","active":1,"version":1}],"next_cursor":1}`.
`after` é o último ID recebido; `limit` é 1..100. Uma página vazia encerra a
varredura. É paginação por chave, não snapshot multirrequisição. Os dados podem
mudar entre páginas. HTTP externo é limitado a 120 requisições/minuto por
credencial, incluindo autenticação inicial WebSocket. Excesso retorna 429;
cliente deve aguardar próximo minuto com jitter. Falta de credencial/escopo,
revogação, expiração e outra empresa retornam 401; ACL removida retorna 403.
A sessão/cookie não substitui Bearer. Respostas de dados usam `Cache-Control: no-store`.

```http
POST /api/companies/1/integrations/webhooks
Content-Type: application/json
X-CSRF-Token: <csrf-da-sessao>

{"credential_id":"<id-retornado>","url":"https://receptor.example.invalid/events"}
```

Destinos `.invalid` são apenas exemplos: a chamada real rejeita DNS ausente.
Não remova a proteção de endereços privados para testes: a suíte injeta transporte
sintético. O destino deve usar credencial do próprio usuário e escopo de entrega.
201 retorna `{id,signing_secret,start_sequence}`. São entregues somente eventos
posteriores à criação. Limite: 100 destinos ativos por instalação.
`DELETE .../webhooks/{id}` revoga; `GET .../deliveries` mostra as 100 entregas mais
recentes da empresa, com tentativa, estado, próximo horário Unix e resultado
categorizado. Para auditoria histórica, use a rotina de auditoria existente.

Crie/edite um centro de custo pela tela existente ou API interna já documentada.
O trigger registra evento na **mesma transação** do cadastro: rollback não deixa
evento; repetição recusada do cadastro não gera duplicata. O evento não copia
nome, valores contábeis, documentos nem segredos:

```json
{"specversion":"1.0","id":"0123456789abcdef0123456789abcdef","sequence":7,"type":"cost-center.changed.v1","time":"2026-11-17T12:00:00.000Z","company_id":1,"data":{"id":3,"version":2,"operation":"updated"}}
```

`operation`: `created` ou `updated`. `sequence` cresce por instalação e pode ter
lacunas de outras empresas; somente eventos da empresa autorizada são retornados.
`GET /integrations/v1/companies/1/events?after=0&limit=100` retorna
`{events,next_cursor}`. ID e corpo persistidos permanecem estáveis nos retries.
A consulta recupera o cadastro atual, não uma fotografia histórica de seu nome.

## Assinatura, entrega e recuperação

Headers: `X-Escritura-Event` (ID estável), `X-Escritura-Timestamp` (segundos Unix),
`X-Escritura-Signature: v1=<hex HMAC-SHA256>`.
Mensagem assinada: bytes ASCII do timestamp + `.` + **corpo bruto exato**.
Verifique em tempo constante e tolere no máximo 300 s de diferença de relógio.
Valide empresa, tipo e versão do contrato. Não parseie/serialize novamente antes
de verificar. O exemplo executável `scripts/integration_inbox.py` mantém ID e
hash em inbox SQLite e grava efeito de negócio na mesma transação. Duplicata
idêntica retorna sucesso sem repetir o efeito; ID repetido com corpo diferente
falha. Falha do efeito desfaz inbox e efeito. O chamador oferece seu servidor HTTPS
 e retorna 2xx somente depois do commit. Nenhum receptor público é iniciado aqui.

O worker da aplicação tenta uma entrega por ciclo de um segundo. Materializa no
máximo 100 pendentes por destino; demais eventos continuam no histórico persistido.
Claim transacional com lease de 60 s permite retomar após interrupção. São no máximo
5 tentativas; atrasos 30, 60, 120, 240 segundos entre falhas. HTTP 2xx confirma;
qualquer outro código, inclusive 3xx, é falha. Destino e todos os endereços DNS
são revalidados a cada tentativa; qualquer endereço não global rejeita o conjunto.
A conexão usa IP resolvido fixado com certificado/SNI do hostname original,
sem proxies de ambiente e sem redirects. Timeout de socket é 5 s; resolução DNS
segue os limites do resolvedor do SO. Não se lê nem armazena corpo de resposta.

Semântica **pelo menos uma vez**: queda após o consumidor gravar, mas antes da
confirmação local, pode repetir evento. Lease expirado também pode repetir uma
tentativa ainda em andamento. Consumidor precisa de inbox idempotente. Não há
garantia de ordem de entrega entre retries; use a versão do recurso e consulte
o estado atual. Expiração/revogação/ACL impedem novos envios; envio já iniciado
pode concluir. Retomada após perda temporária de ACL não reenvia entregas canceladas.

Estados: `pending`, `inflight`, `delivered`, `dead`, `cancelled`. Em `dead`, revisar
configuração/receptor, recuperar pelo endpoint de eventos a partir do último
cursor confirmado e aplicar a mesma inbox. Não há botão/endpoint de redrive neste
incremento. Auditoria registra ID, tentativa e resultado, nunca token, chave,
URL, corpo de resposta ou mensagem bruta de exceção. Após restart, entregas
pendentes persistem. Não existe limpeza automática de histórico/inbox/entregas:
monitorar espaço e preservar cursor; retenção/compactação é trabalho posterior.

## WebSocket e reconexão

Conecte a `/integrations/v1/stream` usando `wss` no ambiente remoto, com Origin
exatamente permitida. Origem ausente é recusada. Não há parâmetros na URL.
Depois de abrir, envie em até 5 s:

```json
{"token":"<segredo-no-frame-nunca-na-url>","company_id":1,"after":0}
```

Servidor valida credencial, escopo `events:read` e ACL antes de qualquer dado.
Cada frame de resposta é `{events:[...],next_cursor:N}`, no máximo 100 eventos.
Depois de processar e persistir os eventos/cursor, envie `{"ack":N}` em até 15 s.
Mesmo um lote vazio precisa de ACK. Há intervalo mínimo de 250 ms por lote.
Não é permitido trocar a empresa/assinatura nessa conexão: abra outra autenticada.

Máximo 3 conexões por credencial e 100 por processo (inclui aguardando autenticação).
Há um lote em voo por conexão, timeout de envio de 5 s, nenhum buffer ilimitado de
produção na aplicação. Origem/protocolo/ACK inválidos, token vencido ou revogado
fecham com 1008; limite de conexões com 1013; frame grande com 1009. ACL e validade
são reavaliadas antes de cada lote; cliente parado é fechado no timeout de ACK
(até 15 s). Heartbeat é lote vazio/ACK, além do ping do transporte.

Reconectar com backoff exponencial e jitter, e `after` igual ao último cursor
**persistido**, não apenas recebido. Repetição após queda é esperada; deduplicar
por ID. Cursor é referência ao histórico, não autorização. Em 1008 renovar
credencial/permissão antes de insistir. Em 1013 aguardar/liberar conexões.

## Operação e lacunas

- Uma instância gravadora SQLite por instalação, como a arquitetura existente;
  não valida múltiplos processos, broker distribuído, PostgreSQL ou HA.
- Inclusões/edições futuras de centros de custo são capturadas; não sintetiza
  eventos retroativos, exclusões físicas ou alterações em outros domínios.
- Gestão é via API interna; não há nova tela de integrações. Clientes HTTP externos
  não recebem acesso às demais rotas da API interna.
- Exemplo de receiver é componente transacional, não servidor pronto para produção.
- TLS externo, DNS real de consumidor, proxy, empacotamento nativo e cargas prolongadas
  precisam de validação no ambiente de destino. Somente dados sintéticos foram usados.
- Criação de tabelas/triggers é aditiva e idempotente. Backup integral SQLite inclui
  fila e credenciais; restauração deve conservar a chave mestra separadamente. Antes
  de reabrir um backup em outra instalação, desabilite destinos/revogue credenciais
  para não reenviar eventos antigos. Não se realizou restauração de produção.
- A implementação do transporte nunca aceita localhost/rede privada; testes de
  webhook usam doubles, enquanto o teste WebSocket abre socket real local.

## Validação reproduzível

```sh
python -m unittest discover -s tests -p test_integrations.py -v
python -m unittest discover -s tests -v
```

O gate existente do CI descobre `test_integrations.py`; não é necessário mudar
workflows. Casos cobrem credencial/escopos, CSRF/contexto, empresa/ACL/revogação,
expiração, paginação/limites, atomicidade do outbox, assinatura/replay/inbox,
SSRF/DNS misto/IP fixado/redirect, retries/dead letter/restart, ciclo de vida do
worker, limites/origem/ACK/reconexão e Uvicorn/WebSocket real com dados sintéticos.
Resultados locais e CI do commit exato devem ser consultados na PR; código de
teste existente, isoladamente, não é evidência de execução nem de homologação.

### Evidência local de 17/11/2026

- Suíte final desta frente: 17 testes aprovados, inclusive TCP/WebSocket real,
  consumidor idempotente, destinos por empresa e revalidação de allowlist.
- Frontend: build aprovado e 202 testes aprovados.
- Regressão ampla: 1.450 testes; primeira rodada teve 3 falhas de infraestrutura,
  4 erros de socket Unix e 44 skips. As 3 falhas foram corrigidas (42 dependências
  no lock e referências derivadas do MinIO) e os 24 testes de infraestrutura
  passaram na repetição. A suíte ampla não foi repetida após esses ajustes;
  as correções de segurança posteriores foram cobertas pela suíte focada final.
- Os 4 testes `SocketBoundaryTests` de `test_docker_updates.py` continuam bloqueados
  por `PermissionError: Operation not permitted` ao criar socket Unix neste
  ambiente; não foram removidos, simulados ou contornados. Permanecem no CI.
- Os 44 skips pertencem a Windows/DPAPI (1), PostgreSQL/driver/ferramentas (35)
  e runtime nativo Apple (8). Não representam validação dessas plataformas.
- Templates alterados somente na tag MinIO derivada da imagem base que contém
  a nova dependência; nenhuma stack, imagem ou release foi implantada/publicada.

Logs locais: `artifacts/integration-focused.log`, `integration-infrastructure.log`,
`integration-regression.log` e `integration-frontend.log` (não versionados).
