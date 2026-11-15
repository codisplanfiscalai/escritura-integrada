# Interface da integração contábil de saídas — incremento sobre a PR39

Base: PR39, `feat/fiscal-sales-daily-accounting-20261115`, commit `e4ca8ccc8ceb8bf57b58c52a9aa78c9bd38b927e`. A documentação de API em `INTEGRACAO_CONTABIL_SAIDAS.md` descreve o inventário anterior e a geração/estorno; este documento registra o incremento de interface.

## Cobertura entregue

A nova entrada **Fiscal → Integração contábil de saídas** abre uma tela independente. Ela usa exclusivamente os serviços de domínio/API da PR39 e os leitores existentes de documentos e modelos. Não altera a tela de lançamentos, o dashboard, o relatório sintético, a importação, os serviços de geração ou o cadastro de planos.

Na empresa ativa:

1. O operador consulta e salva o modo `individual` ou `daily`, com a versão fornecida pela API. Configuração de outra empresa não é reaproveitada. Salvar o modo não gera movimentos, não altera lançamentos anteriores nem muda o plano selecionado pela empresa.
2. A consulta lista somente saídas do exercício, filtradas pela competência de **escrituração**, situação contábil e pesquisa por nota, participante, CFOP ou chave. Emissão aparece separadamente. A lista permite consultar notas já contabilizadas e situações não aptas sem criar efeitos.
3. Somente saídas escrituradas, positivas, não canceladas e sem lançamento são selecionáveis. Selecionar a consulta inclui outras páginas; mudar apenas a página preserva a seleção. Filtros, empresa/exercício/módulo limpam a seleção. O limite técnico de 1000 notas da API é explicitado; a seleção não é truncada silenciosamente.
4. Cada nota exige um modelo selecionado explicitamente. O operador pode aplicar um modelo comum e substituir o modelo de notas específicas. Só modelos ativos, revisados, de saída/ambos e vigentes na escrituração são aceitos na apresentação; a API revalida tudo dentro da transação. Não se deduz conta de venda, classificação ou plano por CFOP/nome/identificador fixo.
5. A geração envia IDs/versões das notas, modelos, versão do modo salvo e uma chave idempotente. No modo diário, **o servidor gera lançamentos efetivamente agregados** conforme a PR39; a interface não simula agrupamento ou antecipa uma quantidade de lançamentos por cálculo paralelo. O resultado informa lançamentos, notas vinculadas e ignoradas, incluindo geração zero.
6. O resultado abre todas as contribuições de cada lançamento; cada contribuição permite abrir a trilha da nota. São mostrados valores próprios, modelo quando permitido, classificação preservada, emissão/escrituração e referências de origem. Partidas do lançamento apresentam contas e valores de débito/crédito. Compensações e evidências anteriores permanecem históricas. Leituras de origem não geram movimentos.

A totalização da seleção usa `BigInt`, inclusive na formatação da parte inteira e dos centavos. A soma de 101 notas de 999.999.999.999,99, por exemplo, permanece exatamente 100.999.999.999.998,99. A interface não envia seus totais calculados para a escrituração; os valores são obtidos e validados pelo servidor.

## Contexto assíncrono, repetição e interrupção

Leituras capturam empresa, módulo e exercício/competência operacional; sequência e contexto recusam respostas e erros antigos. Leituras são abortadas ao trocar contexto, desativar KeepAlive ou desmontar a tela. Respostas de rastreabilidade não reabrem uma janela fechada nem substituem uma consulta posterior. Revogação de permissões limpa os dados e a rastreabilidade apresentados.

As mutações usam `captureContext` no cliente e os controles de sessão/CSRF/contexto da API. Durante a requisição, o editor global identifica **esta operação**, impedindo troca de contexto enquanto há efeito em curso conforme o comportamento do aplicativo. Apenas o responsável que registrou esse editor o libera; uma resposta tardia não remove o editor de outro componente. Essa proteção não cria uma confirmação adicional de negócio. Campos necessários e versões continuam sendo controles de integridade, não certificação fiscal.

Clique repetido envia uma só mutação. Em falha de transporte ou HTTP 5xx, a interface conserva uma intenção congelada. **Repetir a mesma solicitação** envia exatamente a mesma seleção, versões, modelos, histórico e chave. A resposta idempotente é identificada como uma solicitação já processada; não anuncia nova gravação. **Atualizar consulta e parâmetros** consulta o estado atual antes de liberar nova seleção. Se o operador recarregar/sair da tela, os vínculos persistidos e a transação da PR39 continuam protegendo contra nova contabilização das mesmas notas; a intenção em memória não é um histórico persistente de operações.

Erros HTTP de validação/permissão não são exibidos como sucesso. Conflito ao salvar configuração mantém a escolha editada e pede consulta do estado salvo. Competência fiscal/contábil fechada desabilita geração na interface mesmo sob a opção legada permissiva; o servidor conserva sua validação obrigatória na nova integração. Configuração e consultas continuam disponíveis. A política global legada de outros fluxos não foi refatorada.

## Independência do relatório e pendências

O Diário Consolidado existente permanece somente leitura. A tela explica que o relatório apenas consulta lançamentos e que novas seleções contábeis geram complementos, inclusive no mesmo dia, preservando o histórico. Consultar relatório/origens, mudar filtros ou selecionar notas não gera lançamentos.

**A integração continua parcial.** Permanecem pendentes a aplicação automática do modo na importação, a distribuição contábil por itens/classificações e a ligação dos botões individuais anteriores ao novo fluxo. O modelo atual contabiliza o total da nota. Esses limites aparecem na tela; esta entrega não afirma integração fiscal/contábil completa nem altera silenciosamente aqueles fluxos.

A configuração está na nova tela para a empresa ativa, e não foi acrescentada ao editor de uma empresa inativa. Não há histórico persistente de lotes de geração na interface, prévia contábil no servidor, paginação remota ou medição de escala dessa consulta anual. Trilha e repetição usam os serviços já existentes. Nenhuma obrigação fiscal é transmitida ou emitida.

## Validação local

- **325 testes backend/CI/bootstrap passaram em 156,787 s**: regressão dos 300 testes da PR39 mais 25 checks existentes de CI/bootstrap. Não há alteração de serviços de domínio neste incremento.
- **153 testes frontend passaram em 2,650 s**, incluindo 15 testes novos com a lógica real do componente Vue. Cobrem ausência de mutações na consulta, seleção/paginação/filtros, centavos além do inteiro seguro, modelos explícitos/vigência, versões e salvamento repetido, contexto fora de ordem, interrupção/repetição da mesma intenção, erro sem sucesso falso, competência fechada/reaberta, permissões revogadas, rastros fechados/substituídos e KeepAlive/unmount.
- **Build Vite passou**, com aviso existente de bundle acima de 500 kB. O bundle principal passa de cerca de 789 kB da base para cerca de 811 kB; não há afirmação de ganho de desempenho. Nenhuma dependência da aplicação foi modificada.
- **Chromium 141.0.7390.37 + aplicação local/SQLite descartável: seis grupos de verificações passaram**, sem erros de JavaScript. Cenário A: um lançamento individual antigo preservado; duas notas de 0,01 e 10,02 geram um agregado de 10,03; três notas adicionais geram três lançamentos individuais com contas/datas/CFOP distintos; reabertura permite mais um. Cenário B: duas notas geram dois lançamentos isolados. Resultado: A=6, B=2, todos balanceados, sem falhas de FK.
- A requisição diária foi efetivamente executada no servidor e sua resposta abortada no navegador. A repetição enviou a mesma chave/corpo, retornou a operação já processada e manteve hashes de documentos, lançamentos, partidas, títulos e auditoria. Filtros/KeepAlive, rastreabilidade e relatório também preservaram dados. Campos fiscais de todas as notas e o título de 0,01 permaneceram iguais, exceto pelo vínculo contábil esperado.
- Interface conferida em 1600 e 1100 pixels, sem expansão horizontal da página; a tabela larga mantém sua própria rolagem. Não é homologação de todos os dispositivos ou tecnologias assistivas.
- Sintaxe Python/YAML, compilação Vue e `git diff --check` passaram. A base não configura um lint separado.

[Resultado e hashes sintéticos](evidence/fiscal-sales-accounting-ui.json). Os screenshots e o relatório integral são gerados em `artifacts/browser-fiscal-sales-accounting/` e publicados como artefato pelo CI; logs locais são exclusivamente do servidor descartável do teste, não de instalações do usuário.

Comandos principais:

```sh
cd frontend
npm ci --ignore-scripts
npm run build
node --test tests/*.test.js
cd ..
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-sales-browser-deps:/tmp/escritura-daily-test-deps:. \
  python scripts/browser_fiscal_sales_accounting.py
```

Na execução local, Chromium do sistema não iniciou por restrição de IPC. O download do navegador atual do Playwright não produziu um ZIP válido; foi usado Playwright 1.56.0/Chromium headless 141 instalado em diretório isolado de testes. O diretório de dependências DANFE da prova anterior também é isolado. O workflow mantém a instalação de navegador já prevista no projeto. O script aceita `ESCRITURA_TEST_BROWSER` para um executável de teste previamente instalado.

O conjunto de 325 testes foi executado com `PYTHONPATH=/tmp/escritura-daily-test-deps:tests:scripts:. python -m unittest` sobre `test_core test_business test_company_accounting_settings test_account_plans test_global_account_plans test_lazy_account_refs test_journal_participants test_accounting_report_models test_report_models_api test_fiscal_import test_import_revision test_import_reprocessing test_reprocessing_linked_effects test_generated_payables test_import_package_cleanup test_book_cancellation test_bulk_operations test_bulk_security test_operational_settings test_workspace_context test_fiscal_sales_accounting test_ci_release test_browser_script_bootstrap -q`.

## Publicação e convivência

PR encadeada à #39: base `feat/fiscal-sales-daily-accounting-20261115`. O CI acrescenta somente essa base à lista já existente e roda o novo navegador/artefatos com `contents: read`. Depois de integrar a #39, retargetar para develop e repetir os checks; não há merge automático.

A frente #38 permanece intacta: não há diff em DocumentsView, JournalView, DashboardView, core/API, listagem ou indicadores. Docker/volumes #35, SPED #36/#37, releases e Atlas não são alterados. A alteração do CI é limitada ao gate da base encadeada e ao novo teste, devendo preservar outras bases que sejam integradas futuramente.

Não executados suíte integral do repositório, PostgreSQL operacional, instaladores/imagens, escala, dispositivos móveis completos, PVA/Prosoft ou ambientes reais. Somente dados gerados sinteticamente. Publicar código/PR não é implantação; sem produção, dados reais, backups do usuário, merge, release ou deploy.
