# PR68: correções dos roteiros de aceitação

Head investigado: `51d072e4235bc3e2a8da8c3df48f2f2a6038fb8b`; base `2a80b87ce2e2666013dff54dfe678e66a90b54e2` (`dev.41`). [CI original 43991979091](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43991979091), job Linux `133734609627`: falha nos roteiros fiscal e de desempenho. A verificação geral do projeto e PostgreSQL haviam passado. Nenhuma alteração na aplicação, UI, domínio, conta, imposto, workflow ou base.

## Causa 1: importação no processo do roteiro fiscal

`python scripts/browser_fiscal_sales_accounting.py` coloca `scripts/`, e não a raiz do checkout, na entrada do caminho de importação. O servidor filho iniciava corretamente com seu cwd na raiz, mas o processo pai só chegava a `from app.importers import _xml_snapshot` no cenário novo de pagamentos. A CI falhou nessa linha após os 11 grupos anteriores. A validação local inicial havia usado PYTHONPATH incluindo a raiz, mascarando a dependência.

Reproduzido com o mesmo comando de entrada, PYTHONPATH removido e dependências disponíveis em ambiente Python isolado: `No module named 'app'`. Correção: incluir explicitamente a raiz resolvida a partir do arquivo, como os outros roteiros do projeto. O import de Playwright fica em main para permitir testar o carregamento da entrada sem lançar navegador ou exigir essa dependência na etapa anterior à instalação do Chromium.

Novo teste executa o carregamento do roteiro e os imports reais de fixtures por subprocesso `python -I`, com cwd temporário fora do checkout. Não cria API, banco ou navegador e não depende de PYTHONPATH.

## Causa 2: avaliação antes de terminar a coleta de métricas

O observador de requestfinished chama `response.body()` para medir bytes decodificados. Essa chamada cede execução ao Playwright. O DOM e a espera networkidle podem concluir enquanto o callback ainda não acrescentou a requisição à lista. O teste avaliava um snapshot incompleto da lista: somente contexto, exercícios e plano global, sem a leitura de contas.

O comando original de desempenho passou uma vez localmente; portanto a reprodução não foi tratada como determinística sem investigação. Uma execução controlada atrasou somente a leitura do corpo pelo observador de métricas em 1.500 ms, mantendo requisições, respostas e DOM reais. O roteiro anterior falhou exatamente em `len(account_reads) == 1`, com account_reads vazio. O HTML/texto de falha preservado já mostrava Plano de contas, suas contas sintéticas, 22.597 registros e página 1 de 452. Isso demonstra a corrida na coleta, em vez de presumir que o servidor não consultou contas ou que as 50 linhas eram da tela anterior. Os erros Target closed surgiam depois da falha, durante teardown.

Correção: acompanhar callbacks de métricas em andamento e aguardar sua conclusão antes de abrir e fechar a janela de cada medição. A espera é por estado real, limitada a 20 segundos e falha explicitamente se o coletor não terminar. A etapa de contas também aguarda sua resposta HTTP 200, cabeçalho e coluna Acesso antes das 50 linhas.

Todos os limites anteriores permanecem: exatamente uma leitura de contas, page=1, menos de 100.000 bytes decodificados, nenhum catálogo indevido e paginação/identidade da página seguinte. Nenhum erro vira sucesso, nenhuma asserção foi removida e nenhum timeout foi elevado. A injeção controlada é somente diagnóstico, não mede desempenho de produção.

## Validação da correção

[Evidência estruturada](evidence/pr68-ci-fixes.json) registra hashes e resultados finais. Artefatos completos permanecem locais em `artifacts/ci68/`, `artifacts/performance/` e `artifacts/browser-fiscal-sales-accounting/`, todos sintéticos.

- 209 testes frontend passaram; build Vite passou, com aviso existente de chunk >500 kB.
- 97 testes Python passaram em 11 módulos, sem falhas/erros/skip: entrada isolada, preservação de evidência, workflows bloqueantes, rateio, entradas/saídas, idempotência/concorrência, estorno, contexto e prévia documental.
- Roteiro fiscal: 12 grupos passaram sem PYTHONPATH de projeto. Dinheiro/cartão/troco, consolidação, rastreabilidade e repetição após resposta perdida permanecem verificados.
- Desempenho: comando normal e execução controlada com leitura de corpo atrasada passaram. A execução controlada registrou espera por métricas em curso; page=1 teve uma leitura de 12.748 bytes, preservando o limite de 100.000. Não houve erros JS ou secundários nos relatórios concluídos. A repetição adicional do comando normal é registrada na evidência.
- Dependências declaradas, versão dev.41, compilação Python e git diff --check passaram. Frontend não possui comando lint separado. Não houve mudança em app/, frontend/ ou .github/ relativamente ao head investigado.

Comandos usados, com Playwright 1.62.0 e Chromium 151.0.7922.34:

```sh
env -u PYTHONPATH python scripts/browser_fiscal_sales_accounting.py
env -u PYTHONPATH python scripts/browser_performance.py
python -m unittest discover -s tests -p test_browser_fiscal_accounting_entrypoint.py
node --test frontend/tests/*.test.js
npm --prefix frontend run build
```

A regressão isolada é também descoberta pela suíte geral. Para repetir o diagnóstico controlado, envolver temporariamente Response.body do Playwright com uma espera de 1.500 ms somente quando a URL terminar em /accounts e a query page for 1, executar main do roteiro e salvar em --output separado. O wrapper completo usado está preservado localmente em `artifacts/ci68/delayed-account-body.py`; não altera o servidor, a aplicação, as respostas ou os limites. As falhas anteriores foram preservadas separadamente.

## Limites

Suíte backend integral, PostgreSQL e imagens/instaladores não foram repetidos localmente nesta correção; a CI do novo head precisa ser conferida separadamente. Não foram incorporadas branches paralelas de relatórios/DF-e/PDF. Não há transmissão, dados reais, merge, release ou implantação. Os limites funcionais de rateio da PR68 permanecem em RATEIO_PAGAMENTOS_CONTABEIS.md.
