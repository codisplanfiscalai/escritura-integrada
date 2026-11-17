# Integrações v1 — expansão de domínios sobre o PR #69

Esta frente usa a fundação do PR #69, integrado em develop no commit
`4dc688152eca4026a1a0750db9d6c04e46c64182`. A PR #71 foi sincronizada com
develop `5d53aaefc1b50f303e86f4988d66de5387eacdd2` (dev.42) para revisão
somente do delta. A PR #71 permanece em rascunho, sem merge, implantação, acesso
a bases reais ou alteração de workflows.

A API interna da aplicação continua sendo o contrato de operações de negócio.
A expansão acrescenta **projeções de leitura de 37 recursos**, **35 fontes de
eventos** e recuperação de entregas. Isto ainda não significa API externa de
toda a aplicação: há campos, comandos, relatórios e integrações não cobertos,
discriminados abaixo. Não é uma API de leitura arbitrária do banco.

## Autorização

Cada novo escopo possui nome explícito: `documents:read`, `documents:events`,
`documents:webhooks`, `journals:read`, etc. Não há wildcard ou concessão implícita
de um recurso para outro, mesmo quando compartilham uma tabela ou rotina.
Emissão e uso exigem `system.integrations:create`, usuário ativo, acesso à empresa,
e `read` **e** `export` na rotina correspondente. As rotinas que ainda não tinham
`export` passam a declará-lo no catálogo de permissões; nenhuma concessão existente
é ampliada automaticamente por esta migração. O fluxo existente de criação de
usuários ainda aplica os perfis explícitos escolhidos pelo administrador.

Credencial continua restrita a um usuário e uma empresa. Reavaliam-se ACL, escopo,
validade e revogação antes de cada consulta, lote WebSocket e entrega. A fronteira
organizacional permanece o banco/instalação; não foi criado cadastro SaaS de
organizações. Não há permissão administrativa global nova.

Os três escopos antigos (`cost-centers:read`, `events:read`, `webhooks:deliver`)
**continuam exclusivos de centros de custo**. URLs e mensagens antigas sem
seleção de recurso mantêm esse comportamento. A migração não transforma tokens
antigos em acesso a documentos, contabilidade, financeiro ou Auditor.

## Cobertura de leitura e eventos

Todos os recursos abaixo têm coleção paginada e consulta por ID. O contrato de
campos é a projeção explícita em `app/integration_resources.py`; a descoberta
retorna os campos permitidos, nunca SELECT `*` ou seleção de colunas do cliente.

| Recurso | Rotina de acesso | HTTP | Webhook/WebSocket |
|---|---|---|---|
| `cost-centers` | `accounting.cost_centers` | Projeção | Criado/atualizado |
| `company` | `system.companies` | Projeção | Criado/atualizado/excluído |
| `accounts` | `accounting.accounts` | Projeção | Não disponível |
| `journals` | `accounting.journals` | Projeção | Criado/atualizado/excluído |
| `journal-lines` | `accounting.journals` | Projeção | Criado/atualizado/excluído |
| `documents` | `fiscal.documents` | Projeção | Criado/atualizado/excluído |
| `titles` | `financial.titles` | Projeção | Criado/atualizado/excluído |
| `settlements` | `financial.settlements` | Projeção | Criado/atualizado/excluído |
| `bank-transactions` | `financial.reconciliation` | Projeção | Criado/atualizado/excluído |
| `reconciliations` | `financial.reconciliation` | Projeção | Criado/atualizado/excluído |
| `bank-allocations` | `financial.reconciliation` | Projeção | Criado/atualizado/excluído |
| `renegotiations` | `financial.titles` | Projeção | Criado/atualizado/excluído |
| `catalogs` | `fiscal.parameters` | Projeção | Criado/atualizado/excluído |
| `rules` | `fiscal.parameters` | Projeção | Criado/atualizado/excluído |
| `fiscal-imports` | `fiscal.imports` | Projeção | Criado/atualizado/excluído |
| `assessments` | `fiscal.assessments` | Projeção | Criado/atualizado/excluído |
| `tax-adjustments` | `fiscal.assessments` | Projeção | Criado/atualizado/excluído |
| `tax-ledgers` | `fiscal.assessments` | Projeção | Criado/atualizado/excluído |
| `auditor-jobs` | `auditor.analyses` | Projeção | Criado/atualizado/excluído |
| `auditor-catalogs` | `auditor.catalogs` | Projeção | Criado/atualizado/excluído |
| `audit` | `system.audit` | Projeção | Não disponível |
| `participants` | `fiscal.masters` | Projeção | Criado/atualizado/excluído |
| `products` | `fiscal.masters` | Projeção | Criado/atualizado/excluído |
| `services` | `fiscal.masters` | Projeção | Criado/atualizado/excluído |
| `establishments` | `fiscal.masters` | Projeção | Criado/atualizado/excluído |
| `histories` | `accounting.histories` | Projeção | Criado/atualizado/excluído |
| `accounting-models` | `accounting.histories` | Projeção | Criado/atualizado/excluído |
| `fiscal-periods` | `fiscal.periods` | Projeção | Criado/atualizado/excluído |
| `fiscal-exercises` | `fiscal.periods` | Projeção | Criado/atualizado/excluído |
| `accounting-periods` | `accounting.periods` | Projeção | Criado/atualizado/excluído |
| `accounting-exercises` | `accounting.periods` | Projeção | Criado/atualizado/excluído |
| `financial-periods` | `financial.periods` | Projeção | Criado/atualizado/excluído |
| `financial-exercises` | `financial.periods` | Projeção | Criado/atualizado/excluído |
| `social-periods` | `social.periods` | Projeção | Criado/atualizado/excluído |
| `social-exercises` | `social.periods` | Projeção | Criado/atualizado/excluído |
| `accounting-imports` | `accounting.imports` | Projeção | Criado/atualizado/excluído |
| `financial-imports` | `financial.imports` | Projeção | Criado/atualizado/excluído |

`accounts` lê a visão efetiva, incluindo IDs negativos das contas compartilhadas;
a emissão completa de eventos desse recurso precisa acompanhar vinculações e
alterações globais e permanece indisponível. `audit` não produz eventos para
não criar recursão entre auditoria de entrega e nova entrega. Tentativas de emitir
escopos de eventos desses dois recursos são recusadas.

Cadastros mestre são filtrados por tipo. Um token de produtos não consulta
participantes nem históricos contábeis. Períodos/exercícios são separados por
módulo; Social cobre apenas esses controles, não folha de pagamento. Jobs do
Auditor marcados como excluídos não aparecem na leitura e produzem tombstone.

São expostos campos necessários a reconciliação de estado: IDs, versões quando
existentes, datas, totais e estados. Não são exportados BLOBs, originais, XML,
`source_json`, `data_json`, snapshots, senhas, tokens, certificados, resultados
brutos do Auditor ou detalhes JSON livres de auditoria. Alguns recursos são
metadados: apurações/importações/catálogos do Auditor não equivalem à extração
integral do respectivo conteúdo. Não existe promessa de todos os campos da tela.

## HTTP

Emissão continua na API interna, com sessão, CSRF e empresa ativa:

```http
POST /api/companies/1/integrations/credentials
Content-Type: application/json
X-CSRF-Token: <csrf>

{"scopes":["documents:read","documents:events","documents:webhooks","titles:read","titles:events"],"expires_in":3600}
```

Usar o token retornado somente em `Authorization: Bearer <token>` nas consultas:

- `GET /integrations/v1/companies/1/capabilities`: somente recursos, modos e
  campos efetivamente autorizados para aquela credencial no momento da consulta.
- `GET /integrations/v1/companies/1/resources/documents?limit=100&after=42&period=2026-11`:
  `{version:"1",resource:"documents",items:[...],next_cursor:...}`.
- `GET /integrations/v1/companies/1/resources/documents/43`:
  `{version:"1",resource:"documents",item:{...}}`; 404 se não pertencer à empresa.
- `GET /integrations/v1/companies/1/events?resource=documents&after=0&limit=100`:
  eventos somente do recurso escolhido.
- `GET /integrations/v1/companies/1/events?resources=documents&resources=titles&after=0`:
  lote ordenado pela sequência global, exigindo **todos** os escopos selecionados.
  Falha de qualquer escopo recusa toda a consulta. Não misturar `resource` e `resources`.

`limit`: 1..100. Ausência de `after` começa no início, inclusive IDs negativos.
Use exatamente o `next_cursor` recebido. Períodos e exercícios têm IDs compostos,
por exemplo `accounting:2026-11` e `fiscal:2027`; não converter esses IDs em número.

`period` é opcional, `YYYY-MM`, disponível somente quando anunciado em capabilities.
Em documentos e lançamentos representa competência; títulos usam emissão,
transações/baixas/renegociações usam data. Recurso sem esse filtro recusa o parâmetro,
em vez de ignorá-lo. O filtro não substitui autorização. A credencial delega os
exercícios da empresa autorizada, não o exercício transitório da sessão que a emitiu.

Leituras são limitadas/paginadas e não geram efeitos de negócio. Paginação por ID
não é snapshot nem feed de alterações: IDs podem ser reutilizados após exclusões.
Para sincronização incremental use eventos e reconciliação do estado atual.
Comandos de domínio via Bearer não estão implementados; POST nessas coleções
é recusado. As proteções da API interna existente permanecem aplicáveis.

## Eventos, webhook e WebSocket

Tipos dos novos recursos: `<resource>.changed.v1`, por exemplo
`documents.changed.v1` e `journal-lines.changed.v1`. O tipo histórico continua
`cost-center.changed.v1`. Envelope e assinatura permanecem os do PR #69:

```json
{"specversion":"1.0","id":"0123456789abcdef0123456789abcdef","sequence":73,"type":"documents.changed.v1","time":"2026-11-17T01:00:00.000Z","company_id":1,"data":{"id":12,"version":2,"operation":"updated"}}
```

Não há conteúdo de documento/lançamento no evento. `data.version` é `null` quando
não há versionamento da entidade de origem; não é uma versão inventada. Use
`sequence` para ordenar notificações e consulte o recurso para obter estado atual.

Triggers gravam o evento dentro da mesma transação SQLite da operação interna.
Rollback não deixa evento; repetição idempotente da escrituração não gera novos
lançamentos, títulos ou eventos. `deleted` é tombstone: pode representar exclusão
física ou saída de uma projeção filtrada. Mudança de tipo/empresa/identidade em uma
linha produz saída da projeção antiga e entrada na nova, ambas na mesma transação.
Isso não autoriza tais alterações pela API externa.

Uma operação integrada pode gerar eventos de diferentes recursos. Não são
agregados numa transação externa única; consumidores reconciliam o estado
confirmado por ID. A fila não cobre mudanças retroativas anteriores à instalação
da expansão e não inclui tabelas ausentes da matriz.

Criar assinatura de webhook com seleção explícita:

```http
POST /api/companies/1/integrations/webhooks
Content-Type: application/json
X-CSRF-Token: <csrf>

{"credential_id":"<id-da-credencial>","resource":"documents","url":"https://receptor.example.invalid/events"}
```

A credencial precisa de `documents:webhooks` e pertencer ao usuário criador. Cada
assinatura cobre um recurso e uma empresa; pode haver assinaturas distintas na
mesma URL autorizada. `GET .../integrations/webhooks` lista até 100 assinaturas da
empresa, sem chave de assinatura. O header adicional `X-Escritura-Subscription`
identifica a assinatura para selecionar a chave no receptor. Verifique a assinatura
antes de agir; esse header isolado não é autenticação. Allowlist por empresa,
SSRF/DNS público/IP fixado/TLS, ausência de redirects, retries e limites do PR #69
continuam válidos. Os exemplos `.invalid` nunca são destinos reais.

WebSocket aceita a seleção de um recurso, ou vários na mesma conexão:

```json
{"token":"<segredo-somente-no-frame>","company_id":1,"resources":["documents","journals","titles"],"after":0}
```

São aceitos de 1 a 40 nomes, limitados aos recursos implementados, com escopo
`:events` de cada recurso. Não misturar `resource` e `resources`. A autorização
integral é reavaliada a cada lote; perda de um escopo encerra a assinatura inteira.
O lote tem no máximo 100 eventos somando os recursos, com um único cursor global
e ACK. Não pode trocar seleção ou empresa por uma mensagem subsequente. Origem,
limites de conexões/frame, backpressure, expiração e reconexão são os do PR #69.

Ao alterar o conjunto de recursos numa reconexão, não reutilize cegamente um cursor
avançado de outro conjunto: eventos antigos dos recursos adicionados podem ficar
antes dele. Faça reconciliação inicial e escolha um cursor adequado para a nova
seleção. O cursor nunca concede acesso a outros recursos ou empresas.

O receptor de referência aceita tipos adicionais somente mediante `event_types`
explícito, por exemplo `event_types={'documents.changed.v1'}` em
`scripts.integration_inbox.accept`. O padrão antigo continua centros de custo.
Deduplicação por ID e hash de corpo é transacional com o efeito do consumidor.

## Recuperação de entrega esgotada

A rota interna abaixo revalida usuário proprietário da assinatura, empresa,
credencial, escopo, ACL e CSRF; assinatura revogada não pode ser recuperada:

```http
POST /api/companies/1/integrations/webhooks/<assinatura>/redrive
Content-Type: application/json
X-CSRF-Token: <csrf>

{"event_sequence":73,"idempotency_key":"recuperacao-sintetica-0001","reason":"Receptor sintético corrigido"}
```

Somente `dead` pode voltar a `pending`. A mesma chave/motivo retorna `duplicate:true`
sem reiniciar tentativas; mesma chave com outro motivo retorna 409. A chave é
por assinatura/evento. Há no máximo três recuperações explícitas por entrega,
portanto no máximo quatro ciclos de cinco tentativas. O evento mantém ID, corpo
e sequência: o consumidor deve continuar idempotente. Auditoria registra usuário,
referência, número de recuperação e hash do motivo, sem segredo nem texto livre.
Repetir uma requisição não amplia o limite. Entregas canceladas por autorização
não são reativadas por essa rota.

## Dependências e lacunas restantes

- Fundamentação: PR #69; o CI `43993473044` do head `a89549e` foi concluído com
  sucesso. Esse resultado valida a base, **não** este delta.
- A sincronização da PR #71 com develop permite CI próprio pelo filtro existente.
  O resultado deve ser conferido no SHA exato da PR; o CI da fundação não o substitui.
  Nenhum workflow foi alterado.
- Consultas completas de itens/tributos, anexos, resultados detalhados do Auditor,
  relatórios, parametrizações não listadas, recepção DF-e/NFS-e, certificados,
  armazenamento, Prosoft e SPED ainda precisam de contratos específicos. Não houve
  modificação das frentes concorrentes de recepção, pagamentos, prévias ou saúde/logs.
- Escrita de documentos, lançamentos, baixas, importações ou fechamentos por token
  externo não está implementada. Exige delegação de contexto, validações e idempotência
  de comandos próprias; não se encaminha Bearer indiscriminadamente à API de sessão.
- Sem UI nova de gestão, OAuth, rate limit distribuído, multi-organização SaaS,
  HA/broker, retenção/compactação automática ou SLA de latência/carga.
- Webhooks continuam com um envio por ciclo de um segundo e até 100 pendentes por
  assinatura materializados. Eventos além dessa janela permanecem no histórico.
  Mais domínios aumentam armazenamento e atraso sob carga: medir antes de uso intensivo.
- Uma instância gravadora SQLite. Não há suporte declarado a downgrade do esquema
  após instalar fontes de eventos novas. Backup conserva banco; chave mestra fica
  separada, conforme o contrato anterior. Não se restaurou nem alterou produção.

## Verificação

`python -m unittest discover -s tests -p 'test_integration*.py' -v` cobre os
contratos antigos e novos, seleção de múltiplos recursos, direitos de operador,
negações por recurso/empresa, toda fonte de evento declarada com fixtures sintéticas,
atomicidade/repetição de escrituração, migração de entrega antiga, tombstones,
IDs compostos/negativos, assinatura, recuperação idempotente e limites. Testes de
triggers com SQL sintético não substituem validação das regras de negócio; os
fluxos internos existentes são verificados também pela regressão da aplicação.

### Resultado local desta expansão — 17/11/2026

- Regressão completa: 1.465 casos, 1.417 aprovados, zero falhas de asserção,
  quatro erros de ambiente e 44 skips, em 768 segundos. Os quatro erros são os
  `SocketBoundaryTests` de `test_docker_updates.py`: criação de socket Unix retorna
  `PermissionError: Operation not permitted`. Permanecem sem contorno no código.
- Os 30 testes de integração (17 preservados do PR #69 e 13 novos) passaram na
  regressão completa, incluindo a fixture corrigida de contexto do usuário fiscal.
- Frontend: build aprovado e 202 testes aprovados. Nenhuma dependência ou workflow
  foi alterado. Sintaxe Python, whitespace e sincronização de templates aprovados.
- Skips: Windows/DPAPI (1), PostgreSQL/driver/ferramentas (35), runtime Apple (8).
  Não são evidência de execução local nessas plataformas. O CI aprovado do PR #69
  é evidência separada da base, não substitui CI desta expansão.
- Logs locais não versionados: `artifacts/domains-regression.log` e
  `artifacts/domains-frontend.log`. As primeiras rodadas focadas registraram erros
  de fixture corrigidos; o resultado final está na regressão completa.

### Verificação após sincronização com develop dev.42

- 30 testes de integração, 19 do núcleo e nove de prévias aprovados.
- 206 testes frontend aprovados; instalação e build concluídos.
- A regressão completa acima pertence ao incremento anterior à sincronização;
  não foi repetida integralmente nesta etapa. O CI próprio verifica o novo head.
