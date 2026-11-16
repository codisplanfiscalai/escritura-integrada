# PR39 — composição com develop dev.13 antes do merge final

Esta atualização integra a `develop` na branch da PR39 por **merge com dois pais**, sem rebase, squash, force push ou alteração da PR42. Não faz o merge final da PR39 para develop.

Referências verificadas antes de escrever:

| Referência | SHA |
| --- | --- |
| PR39 original, `feat/fiscal-sales-daily-accounting-20261115` | `e4ca8ccc8ceb8bf57b58c52a9aa78c9bd38b927e` |
| Base original da PR39 | `3a6ab4c58f5c48aa0ea383cc2beeff615172ce71` |
| **develop efetivamente composta e testada** | **`a8ac6902aab76ebe66444d2818ea0cbd9c65e4d4`**, `0.9.0-dev.13` |
| PR42, `feat/fiscal-sales-accounting-ui-20261115` | `8a74a6846004f6d5e0bb14f4c334edd49405f3a3` |

A develop avançou exatamente 21 commits desde a base original e inclui #38 (consultas contábeis/indicadores), #36/#37 (SPED) e #35 (armazenamento Docker). O CI anterior da PR39, [43688520088](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43688520088), estava concluído com sucesso. A PR39 permanecia aberta em rascunho; a PR42 continuava encadeada à mesma branch da PR39.

## Resultado da composição

O merge local de develop na PR39 não apresentou conflitos textuais. `app/core.py`, `app/api.py` e `app/permissions.py` foram compostos automaticamente e conferidos antes dos testes. Não foi necessária correção funcional nem refatoração. Esta atualização acrescenta somente seis provas de composição e a documentação/evidência, além do conteúdo da develop.

Comparação verificável de fontes:

- `Core._journal`, `Core.journals` e `Core._normalize_lines` são semanticamente idênticos à develop testada. A leitura otimizada mantém snapshot, filtros SQL e partidas em lote.
- `Core._create_journal` é semanticamente idêntico ao head original da PR39, preservando `source_reversal`, permissões e estorno da contribuição individual sem reverter todo o agregado.
- `app/business.py`, `app/fiscal_sales_accounting.py`, `app/reports.py` e os 35 testes originais da PR39 estão byte a byte iguais ao head original.
- **196 arquivos** de frontend, SPED, deploy, scripts, workflow, versões e testes relevantes estão byte a byte iguais à develop testada. Nenhum código da PR42 foi trazido para esta branch.
- Os registros da integração contábil e do Gerador SPED coexistem na API. A permissão de exportar documentos não concede criação contábil.

Os hashes de blobs, hashes de AST das funções e manifesto agregado de todos os arquivos rastreados de `app/` estão em [evidence/pr39-develop-composition.json](evidence/pr39-develop-composition.json). Os testes foram executados sobre a árvore de trabalho já composta, antes do commit de merge; por isso o roteiro de navegador existente registra em `source_sha` o primeiro pai original. Os fingerprints identificam o código efetivamente testado; a publicação deve conferir a árvore remota contra essa mesma árvore local.

Não há novas restrições operacionais. Mantêm-se o escopo por nota/dia, a geração complementar em seleções posteriores, idempotência, vínculos, permissões, isolamento de empresas e estorno parcial da PR39. A configuração e o histórico não são migrados silenciosamente. A revisão pendente dos documentos importados continua um aviso informativo conforme o fluxo existente; escrituração importada não significa conferência registrada.

## Seis provas novas, com fixtures sintéticas

`tests/test_fiscal_sales_composition.py` usa os serviços reais de importação, escrituração, contabilização, leitura e exportação:

1. **Listagem otimizada após geração diária, individual e estorno parcial:** três SELECTs no serviço, igualdade exata de cabeçalhos/partidas com a consulta individual e com a API, separação de empresa, ano e competência; dados permanecem intactos nas leituras.
2. **Contabilização diária versus SPED individual:** três NFC-e importadas/escrituradas geram um lançamento contábil de 300,00, enquanto o Bloco C continua com três C100 e o mesmo conteúdo/trilha anterior à contabilização. A prévia SPED não cria lançamentos.
3. **Estorno parcial e reescrituração:** uma nota compensada volta a pendente pelo serviço existente, as outras duas continuam escrituradas; a exportação parcial abrange somente as duas escrituradas. O saldo econômico reflete a compensação, o agregado original permanece intacto e a nova escrituração/contabilização explícita restaura o valor. O ZIP sintético original continua byte a byte igual, com FK válida.
4. **Competência fechada/reaberta:** SPED e relatório continuam somente leitura durante o fechamento; a nova contabilização é recusada sem gravações. Reabrir permite a contabilização, mantendo a exportação por nota.
5. **Exportador nativo opcional:** com lançamentos contábeis existentes, exportação desligada devolve o original e a opção ligada continua com sua consolidação fiscal nativa; nenhuma delas modifica movimentos.
6. **Permissões compostas:** operador autorizado a consultar/exportar documentos consegue gerar o Bloco C parcial, mas recebe 403 ao tentar criar lançamentos sem concessão contábil. O banco sintético permanece igual.

O SPED continua parcial, não homologado no PVA nem transmitido. Consolidação fiscal/visual e consolidação contábil permanecem independentes.

## Verificações executadas

- **585 testes backend/infraestrutura, em 41 módulos: OK**, sem falhas, erros ou skips. Incluem as seis provas novas, os 35 testes da PR39, consultas otimizadas, SPED, importação/reprocessamento, limpeza de lotes, contas globais/próprias, centavos, idempotência/concorrência, competência fechada/reaberta, cancelamento/estorno e relatórios somente leitura. Runner: **213,145 s**; carregamento + execução: **214,286 s**.
- **141 testes frontend: OK**, 2,890 s, incluindo competência dos indicadores e contexto assíncrono da #38.
- **Build Vite dev.13: OK**. Aviso existente de bundle acima de 500 kB; bundle principal 789,22 kB. Não houve alteração de dependências.
- **Chromium headless 141, aplicação local e SQLite descartável:** roteiros `browser_workspace_context.py` e `browser_document_summary.py` passaram, respectivamente seis e quatro grupos de verificações, sem erros de JavaScript. Indicadores fiscais/contábeis acompanharam agosto/setembro e empresa, preservando novembro operacional; filtros/páginas/KeepAlive/F8/F9 mantiveram os dados. Hashes de documentos, lançamentos, partidas, títulos e auditoria permaneceram iguais nas consultas.
- Sintaxe Python/YAML, paridade de versões dev.13 e `git diff --check` conferidos. A base não oferece um lint Python/JavaScript separado.

Todos os testes finais isolam a aplicação global antes de carregar fixtures, além dos bancos temporários de cada caso. O módulo novo também isola seu import quando executado diretamente. Dependências DANFE e Playwright/Chromium usadas localmente são as instalações isoladas de testes já preparadas; não se alteram dependências do aplicativo. Testes de infraestrutura simulam subprocessos/artefatos; não executam migração Docker nem contato com instalações reais.

O JSON de evidência contém a lista exata dos 41 módulos, contagens/tempos, resultados de navegador e fingerprints das fontes. Comando equivalente da regressão: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-daily-test-deps:tests:scripts:. python` com `TemporaryDirectory`, `ESCRITURA_DATA_DIR` e `ESCRITURA_DEMO=0` definidos **antes** do carregamento da suíte `unittest`.

## Limites e próximo passo

Não foi executada a suíte integral do repositório, PostgreSQL operacional, instaladores/imagens, PVA/Prosoft, escala de produção ou falha de energia. Não foram usados dados reais, backups do usuário, logs privados ou produção. O CI novo precisa ser conferido no SHA publicado; sucesso do CI antigo não valida esta composição automaticamente.

A PR42 fica com o mesmo head e a mesma branch-base, sem retarget, rebase, atualização ou merge nesta tarefa. Sua validação contra a nova base é um passo posterior. Importação automática e distribuição contábil por itens seguem pendentes; este preparo não amplia a cobertura funcional da PR39 nem incorpora a interface da PR42.

A publicação atualiza somente `feat/fiscal-sales-daily-accounting-20261115`, conferindo o head esperado e a árvore validada, sem forçar a referência. Não atualiza develop, não fecha/integra PRs e não realiza release ou deploy.
