# Integração contábil de saídas fiscais — incremento de API

Base inventariada: `develop` em `3a6ab4c58f5c48aa0ea383cc2beeff615172ce71`.
Não foram encontrados `AGENTS.md` nem `.agents/skills` nessa árvore Git.

## Cobertura anterior e escopo

| Caminho existente | Comportamento anterior preservado |
| --- | --- |
| `BusinessCore._book_document` / `Core._book_document` | Escrituração fiscal individual; gera um lançamento individual somente quando o operador fornece partidas ou modelo. Pode gerar títulos explicitamente. |
| `BusinessCore.account_document` | Contabilização posterior individual de nota já escriturada, com modelo ou partidas explícitas, sem alterar versão fiscal nem títulos. |
| `FiscalImportMixin` / `ImportReprocessingMixin` | Importação/escrituração usa os serviços de domínio; reprocessamento não recria nota existente e recusa reclassificar efeitos contábeis vinculados. |
| `ReportsMixin.business_report('consolidated-diary', ...)` | Relatório diário agrupado por conta e centro; já existia, somente consulta. **Não gera lançamentos contábeis consolidados.** |
| `BusinessCore.reverse_document` | Reverte efeitos financeiros próprios e estorna o lançamento individual vinculado. |
| `accounting_settings`, planos globais e `account_refs` | Configuração por empresa, contas próprias ou referências a plano global selecionado. Sem plano fixo para vendas. |
| `import_package_cleanup` | Retém movimentos e evidências normalizadas quando remove o pacote original/histórico do lote. |

Os 50 testes de `test_business`, `test_company_accounting_settings`, `test_reprocessing_linked_effects` e `test_book_cancellation` passaram antes da implementação, em 19,167 s.

O incremento acrescenta **um serviço explícito em lote para contabilizar saídas já escrituradas**, com modo persistido por empresa. Não altera os contratos de geração individual anteriores. Ainda não conecta o modo aos botões de contabilização individual, à escrituração automática na importação nem a uma nova interface de seleção em lote. Isso é pendência funcional explícita; escolher `daily` nesta API não transforma silenciosamente os fluxos antigos.

## Contrato

Todas as rotas começam com `/api/companies/{cid}/fiscal-sales-accounting` e usam a mesma sessão, CSRF, isolamento de empresa, exercício, permissões e transações do aplicativo.

- `GET /settings`: `{version, mode, notice}`; padrão `individual`, versão 0.
- `PUT /settings`: `{version, mode: "individual" | "daily"}`. Persistência versionada em `meta`, com auditoria. Não altera movimentos. Permissões de leitura/edição de contas; escrita exige a empresa ativa como as demais operações dessa nova API.
- `POST /generate`: `{settings_version, idempotency_key, reason?, entries: [{document_id, version, model_id}]}`; 1 a 1000 notas distintas. Usa modelo contábil existente, ativo, validado, vigente e compatível com a direção, selecionado explicitamente para cada nota. Não configura contas, classificações ou movimentos por inferência. Permissões: criar lançamentos, ler documentos e ler modelos contábeis; revalidadas na transação.
- `GET /journals/{id}/sources`: lançamento, todas as contribuições de notas e compensações registradas, com leitura contábil e fiscal. Na geração, empresa, exercício de escrituração e contexto da operação são protegidos pelas fronteiras existentes.
- A trilha existente `GET /documents/{id}/trace` passa a incluir `accounting_sources` quando há permissão de leitura contábil. Snapshots de modelos são omitidos para quem não pode ler históricos/modelos contábeis.

A resposta da geração discrimina `created_count`, `accounted_count`, `journals`, `sources` e `skipped`. Nota com lançamento permanece intacta e aparece como `already_accounted`; pendente, não escriturada, cancelada ou de valor zero aparece como `not_eligible`. Entrada fiscal, configuração ausente/inválida, versão obsoleta, referência de outra empresa ou falha contábil geram erro e rollback integral. Um lote sem notas elegíveis informa **zero** lançamentos gerados, com seus motivos; não declara contabilização concluída de notas ignoradas.

A consulta de fontes é histórica: conserva contribuições mesmo depois de estorno, nova escrituração ou exclusão explícita dos movimentos. O endpoint da nota permite confrontar os eventos e lançamentos atuais. A reprodução da mesma chave é uma resposta histórica idempotente, não uma regeneração nem uma leitura do estado atual da nota. Exclusão física por operações em lote invalida a reprodução conforme o mecanismo já existente; ela retorna `movement_deleted`.

## Geração individual e diária efetiva

`individual` cria um lançamento por nota elegível. `daily` cria um lançamento por grupo dentro **da seleção da requisição**, com partidas efetivamente somadas em centavos inteiros, mantendo balanço entre débito e crédito.

A chave de agrupamento inclui:

1. Data de escrituração da nota, independente da data de emissão.
2. Modelo fiscal, CFOP do cabeçalho e conjunto de classificações dos itens/analíticos normalizadas pelo mesmo leitor do livro fiscal (`cfop`, `cst_icms`, `csosn`, origem, alíquota e tratamento), além de NCM/ClassTrib/EXTIPI explícitos e códigos tributários declarados em caminhos XML (`CST`, `CSOSN`, `cClassTrib`, `orig`, `cEnq`), quando existentes. O C190 do SPED tem precedência sobre itens, como no livro fiscal.
3. Contas operacionais de débito/crédito, lado da partida, centro de custo e participante de cada partida. Referências globais são resolvidas/materializadas pelo serviço já existente, sem copiar definições globais nem escolher plano por identificador fixo.

Modelos diferentes que apontem para as mesmas contas/dimensões podem compartilhar o grupo; o snapshot de cada modelo fica associado à sua nota. Notas com assinaturas heterogêneas são separadas. **Não há rateio contábil por item, alíquota ou tributo:** o modelo existente contabiliza o total da nota. Documento com várias classificações conserva o conjunto da assinatura e sua contribuição total; não inventa uma distribuição entre itens. Um incremento posterior deverá permitir distribuição contábil explícita quando necessária.

Cada contribuição gravada na trilha de auditoria existente contém empresa (coluna da auditoria), ID/número/série/chave/versão fiscal da nota, emissão, escrituração, hash da origem, classificação, snapshot do modelo, partidas e valor próprio, além de ID do lançamento e modo utilizado. Não depende da retenção do XML/lote, não exige migração de schema e não recalcula o histórico usando modelos alterados posteriormente.

Trocar modo só afeta futuras notas desta integração. Notas com `journal_id` são sempre preservadas, mesmo sob outra chave de processamento. **Uma seleção posterior cria lançamento complementar** para suas novas notas, inclusive na mesma data/classificação. Não reabre nem soma silenciosamente a um lançamento anterior, não migra o histórico e não promete um único lançamento por dia ao longo de várias requisições. A resposta explica essa regra em `notice`.

A transação `BEGIN IMMEDIATE`, o vínculo fiscal existente e as chaves únicas contábeis/operações protegem contra repetição e solicitações concorrentes com chaves distintas. Chave contábil inesperadamente já usada fora da operação não é reaproveitada para vincular novas fontes. Falha ou interrupção desfaz partidas, vínculos, referências materializadas e auditoria da tentativa.

## Estorno e competência

O estorno continua pelo serviço `reverse_document`, com seus controles financeiros existentes. Para notas desta integração, usa a contribuição persistida da nota e cria somente sua compensação, invertendo as partidas originais. O lançamento compartilhado e as demais notas permanecem intactos. Isso também vale para grupos com uma nota: o histórico do lançamento original é preservado, e a compensação fica explicitamente ligada pela auditoria, sem marcar todo o agregado como estornado em `reversed_by`.

`Core._create_journal` recebe uma opção **interna**, `source_reversal`, para exigir permissão de estorno e permitir contas/participantes históricos inativos como os estornos anteriores. Nenhuma rota aceita esse campo do cliente. A compensação passa pelo mesmo normalizador, numeração, validação de balanço, controle de competência e auditoria dos demais lançamentos. Não exige permissão de inclusão ao operador que só pode estornar.

Estornar diretamente um lançamento de origem ou uma compensação desta integração pela rota genérica de lançamento é recusado para preservar o controle do documento, mesmo depois de todas as notas se desvincularem. A falta de evidência de contribuição num lançamento compartilhado não autoriza estornar o grupo inteiro. Reescriturar/contabilizar de novo exige reversão explícita anterior e nova intenção/chave; a trilha anterior permanece.

Para este novo serviço, competência fiscal e contábil de origem fechadas exigem reabertura; o mês contábil de destino do estorno também. Essa regra vale mesmo se `enforce_period_locks` estiver desligado nas opções legadas. Não há alteração ampla dessas opções nos demais fluxos. A consulta de parâmetros/fontes e o relatório continuam disponíveis em competência fechada. Alterações/exclusões existentes continuam sob os serviços anteriores; a política legada global é uma pendência independente, não foi refatorada aqui.

## Relatório sintético independente

O relatório existente `GET /api/companies/{cid}/business-reports/consolidated-diary?start=...&end=...` continua acessível na interface de Relatórios, com filtros e formatos existentes. Ele agrega os lançamentos atuais por dia/conta/centro e lista seus `journal_ids`. A descrição agora explicita que é somente leitura e não gera nem altera lançamentos. Funciona independentemente do modo escolhido, incluindo notas contabilizadas individualmente, e inclui as compensações existentes no período selecionado. Não transforma a exibição em consolidação contábil nem promete relatório fiscal legal.

## Convivência e limites

- Base `develop` dev.9; não altera Docker/volumes (#35), Gerador SPED (#36/#37), Atlas, releases ou deploy.
- Em `core.py`, só a assinatura e as escolhas internas de permissão/normalização/auditoria de `_create_journal` são alteradas. Não toca `_journal`, `journals`, dashboard ou filtros da #38; não reverte sua frente.
- Não há autoidentificação de conta de venda, plano 050 obrigatório, identificador DIX, geração de saldo nem emissão/transmissão fiscal.
- Permanecem: UI da nova integração/configuração, ligação explícita dos fluxos individuais/importação ao modo, prévia de seleção, distribuição contábil por itens/classificações, medições de escala e homologação operacional. O modo persistido e o serviço em lote são utilizáveis via API, mas não representam entrega completa desses fluxos de UI.
- PostgreSQL do aplicativo, PVA/Prosoft, instalações Windows/macOS, rede/concorrência de produção e instalações reais não foram homologados. Não foram usados backups, dados reais, XMLs privados, credenciais ou produção.

## Validação

Os comandos finais, contagens e limites são registrados abaixo após a execução. Os testes novos entram automaticamente na descoberta de `tests` do CI existente. Não há lint Python/JavaScript configurado na base; sintaxe e `git diff --check` são os checks estáticos aplicáveis.

Resultados finais locais:

| Verificação | Resultado |
| --- | --- |
| Referência anterior, 4 módulos | 50 testes, 19,167 s, OK antes da alteração |
| Backend final, 21 módulos abaixo | **300 testes, 143,795 s, OK**: 35 novos e 265 regressões; contagem inclui os testes de referência aplicáveis, não deve ser somada às rodadas anteriores |
| Frontend preservado | **138 testes, 2,227 s, OK** |
| Build Vite 7.3.1 e coleta de avisos | OK; aviso existente de chunk acima de 500 kB (bundle principal 788,97 kB) |
| Sintaxe Python | `ast.parse` nos 7 arquivos Python novos/alterados, OK |
| Whitespace/patch | `git diff --check` e check do diff staged, OK |

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-daily-test-deps:tests:scripts:. python -m unittest \
  test_core test_business test_company_accounting_settings test_account_plans \
  test_global_account_plans test_lazy_account_refs test_journal_participants \
  test_accounting_report_models test_report_models_api test_fiscal_import \
  test_import_revision test_import_reprocessing test_reprocessing_linked_effects \
  test_generated_payables test_import_package_cleanup test_book_cancellation \
  test_bulk_operations test_bulk_security test_operational_settings \
  test_workspace_context test_fiscal_sales_accounting -q

cd frontend
npm ci --ignore-scripts
npm run build
node --test tests/*.test.js
```

O diretório temporário no `PYTHONPATH` contém apenas dependências de teste: `BrazilFiscalReport==1.3.1` (já exigida em `requirements.txt`) e suas dependências. A primeira rodada ampla teve uma falha porque esse pacote não estava instalado no ambiente; ele foi instalado isoladamente e as regressões foram repetidas com sucesso. Nenhuma dependência da aplicação foi modificada. Há aviso de depreciação do TestClient/httpx; não houve falha na rodada final.

As 35 provas novas cobrem: comportamento anterior; geração individual versus diária real; múltiplas datas, contas, CFOP/CST/alíquotas/ClassTrib, centros, participantes e empresas; centavos; origem completa por nota e consulta inversa; configurações persistidas e mudança de modo; inclusão complementar; repetição com mesma chave, conflito de conteúdo e nova chave; concorrência; versões/contexto obsoletos; configuração ausente/inativa; interrupção com rollback e repetição; fechada/reaberta inclusive sob opção legada permissiva; estorno parcial e total econômico, títulos preservados/cancelados pelo documento, somente permissão de estorno e contas inativas; canceladas/pendentes ignoradas com motivo; plano compartilhado e desassociação para próprio preservando IDs; reimportação/reprocessamento; limpeza de pacote; exclusão explícita em lote e invalidação da reprodução; evidência ausente e colisão de chave; relatórios repetidos/filtrados/vazios somente leitura, com snapshot de todas as tabelas sintéticas preservado; permissões revogadas e ocultação dos modelos sem acesso.

Não foram executados suíte integral do repositório, navegador neste incremento sem UI nova, builds de instaladores/imagens nem ambientes externos. O CI remoto deve ser conferido no PR; aprovação local não representa implantação.
