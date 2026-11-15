# CI PR44: coleta da consulta CFOP após importação

A execução [43692650933, job 132746339950](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43692650933/job/132746339950) falhou no smoke Chromium em `browser_fiscal.py`, na consulta auxiliar `page.request.get(.../cfop-source-loads)`.

## Evidência e reprodução

O artefato `browser-evidence` foi inspecionado separadamente da árvore Git. O `server.log` mostra POST de importação 200, consultas GET da interface 200 e a nova prévia 200; não contém erro 500, traceback ou queda do servidor nesse trecho. O GET auxiliar do `APIRequestContext` que reportou `socket hang up` não aparece no acesso do servidor. O relatório não registrou erro JavaScript de página. O job de testes do projeto e o navegador específico Prosoft passaram; a falha ocorreu no smoke fiscal geral.

O `page.request` é um cliente HTTP do driver Playwright, distinto das requisições feitas pela página, embora compartilhe os cookies do contexto. A implementação instalada do Playwright 1.62 usa agente HTTP com keep-alive. O servidor de smoke usa o timeout padrão de keep-alive do Uvicorn instalado, de cinco segundos.

A hipótese de reuso de conexão no instante de expiração foi testada contra **o mesmo endpoint real**, em servidor e SQLite descartáveis. O reproduzidor `scripts/diagnose_cfop_keepalive.py` instrumenta a entrada no handler e o callback de expiração da conexão; não registra cookies/cabeçalhos e não aceita URL ou diretório de dados externos. Encurtar o timeout só nesse processo diagnóstico permite observar a corrida rapidamente. Não muda o servidor de produção, o servidor normal de smoke ou o cliente do produto.

Resultado local de uma execução de 270 GETs por condição:

| Timeout ocioso do servidor diagnóstico | GETs medidos | Erros do cliente | GETs com erro que chegaram ao handler | Erros com expiração da mesma conexão dentro da chamada |
|---|---:|---:|---:|---:|
| 20 ms, chamadas junto ao limite | 270 | 10 (`socket hang up` / `ECONNRESET`) | 0 | 10 |
| 200 ms, mesmas pausas/chamadas | 270 | 0 | 0 | 0 |

O endpoint permaneceu saudável e não gerou erros de aplicação nas duas condições. O mecanismo reproduz o sintoma do CI e a ausência do pedido no handler: o probe Node reaproveita uma conexão no instante em que o servidor a encerra por ociosidade. O CI original não possui captura TCP nem timestamps de fechamento, portanto o instante exato da corrida naquele run é inferido da evidência disponível; o mecanismo foi observado diretamente no reproduzidor. A contagem pode variar com o agendamento. Isso não estima frequência em produção nem desempenho do servidor.

## Correção

O smoke agora observa o **POST e o GET que a própria interface executa após importar**, em vez de emitir uma segunda consulta pelo pool Node depois de vários passos de UI. O observador é limitado à URL e aos métodos esperados; consultas iniciadas antes do POST não são aceitas. Ele é removido ao concluir ou falhar.

A espera pelo botão “Carga já importada nesta empresa” continua. O fluxo existente do componente é `apply → reload → prepare`: esse estado vem após recarregar a lista e obter a prévia de carga já importada. As verificações originais continuam exigindo uma única carga, 779 registros e parâmetros inativos. Foram acrescentadas verificações explícitas de sucesso HTTP do POST/GET e de que o ID consultado é o da carga recém-importada. Erro HTTP, JSON inválido ou lista ausente/incorreta continua reprovando o teste.

Não há retry, aumento de timeout, desativação de keep-alive, remoção de etapa ou mudança de dados/rotas/configuração da aplicação. A política de importação, confirmações, permissões, competência e parametrização fiscal permanece igual. Não foi alterado comportamento com base em conversas históricas.

## Validação local

- **40 testes passaram em 16,163 s**: seis novos testes das verificações de resposta e regressões CFOP/importação/bootstrap/contratos de navegador.
- Novos testes recusam HTTP 401/403/404/409/500/503 no POST ou GET, lista vazia/múltipla, contagem diferente, parâmetros ativados, ID antigo e JSON inválido/sem campos esperados. Nenhum desses casos vira sucesso por fallback.
- Todo `browser_fiscal.run` foi executado isoladamente no Chromium Headless Shell 141, com servidor/banco sintéticos e a política estrita de competências habilitada como no smoke completo. Passaram carga de referência, associação, importação direta, edição motivada, reimportação, conferência posterior, preservação de títulos/partidas, cobrança XML, parcela opcional e cancelamento. Sem erros JavaScript de página.
- Um segundo ensaio de navegador injetou **HTTP 500 no GET real da interface após importar**. O teste reprovou exatamente com esse erro, comprovando que a correção não o mascara.
- O reproduzidor publicado produziu a tabela acima e correlacionou cada erro com o fechamento da conexão, sem requisição recebida pelo handler.
- Sintaxe Python e `git diff --check` conferidos. Código de aplicação, dependências, build de interface e workflow intactos nesta correção.

O smoke completo local ficou bloqueado antes do trecho CFOP porque o Headless Shell 141 disponível não concluiu a abertura da prévia PDF em `browser_exports.py`. A tentativa isolada de obter o Chrome for Testing 151 usado no CI recebeu ZIP inválido e não foi usada. Essas limitações não foram contornadas nem as verificações PDF alteradas. O smoke completo continua obrigatório no novo CI remoto da mesma PR, que usa Chromium 151.

Comandos reproduzíveis, com as dependências do projeto e Playwright instalados:

```bash
PYTHONPATH=tests:. python -m unittest test_browser_cfop_checks test_cfop_source test_rebuilt_browser_contracts test_browser_script_bootstrap test_fiscal_expansion test_fiscal_import -v
PYTHONPATH=. python scripts/diagnose_cfop_keepalive.py --samples 270
PYTHONPATH=. python scripts/smoke_browser.py
python -m compileall -q scripts/browser_fiscal.py scripts/browser_cfop_checks.py scripts/diagnose_cfop_keepalive.py tests/test_browser_cfop_checks.py
git diff --check
```

`ESCRITURA_TEST_BROWSER` pode selecionar um Chromium instalado para o diagnóstico. Seus arquivos são gerados somente em `artifacts/cfop-keepalive-diagnostic/`; não são incluídos no Git. Os logs baixados do CI, perfis de navegador, bancos temporários e pacotes recebidos não foram publicados.
