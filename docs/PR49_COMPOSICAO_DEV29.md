# PR49 — composição com develop dev.29

Atualização apenas de `feat/fiscal-accounting-incoming-20261116`, por merge sem rebase/force push, em nova worktree isolada. Head público anterior: `d39963a66de08ca0ec5c0b03928bc2771f71eb81`; seu [CI 43818810497](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43818810497) passou. **Base composta/testada: `4e031a1b34ea695d8768af4d30224197d9178ea3`, dev.29**. Esses são, nessa ordem, os dois pais do merge de sincronização. Não há `AGENTS.md` ou `.agents/skills` no checkout.

A PR52 foi consultada no head `448f60826f2bff8bc9884da92f73a67f2c8d31a0`, aberta/em rascunho, com [CI 43875031879](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43875031879) em andamento. Seu roteiro Prosoft reaproveitado é byte a byte igual ao da PR49, inclusive espera de contexto, confirmação da guia fiscal e latência de 750 ms. Nenhuma alteração desta tarefa é enviada à PR52, às outras branches ou à develop. Merge final continua reservado à coordenação após publicações e decisão da PR52; não é realizado nesta atualização.

## Composição preservada

O merge foi automático, sem conflitos. `App.vue` recebe a reorganização de Cadastros da develop e mantém **Fiscal → Integração Contábil** e **Contábil → Integração Fiscal**, na mesma tela/processo. `permissions.py` conserva tanto as permissões da integração quanto as novas regras de Cadastros/Contribuições.

Serviço, tela, teste Vue, roteiros de integração/Prosoft e testes originais de entradas/composição Prosoft permanecem idênticos ao head anterior. Todas as verificações Prosoft, incluindo a correção de navegação assíncrona e o timeout anterior, são preservadas. Dos **132 arquivos backend** comparados com a develop, somente serviço/permissões originais da PR49 diferem. Core, API principal, Cadastros, NFC-e, Prosoft, Contribuições e os três workflows recebidos de develop permanecem íntegros, sem modificação manual.

Entradas continuam individuais, com fornecedor/modelo/contas explícitos. Saídas mantêm individual ou consolidação diária por data/classificação/contas/dimensões. Competência é a de escrituração; fechamento, reabertura, permissões, rastreabilidade e idempotência permanecem. Relatórios, prévias e preparação de Contribuições são consultas independentes; não geram lançamentos nem obrigações.

## Validação efetiva

- **763 testes de regressão em 57 módulos: OK**, sem falhas/erros/skips, 374,523 s incluindo carregamento. Abrangem integração, Prosoft, permissões, estorno, planos, reprocessamento, consultas otimizadas, Cadastros, Contribuições, NFC-e e os novos contratos/políticas de CI.
- **Duas provas novas de composição em um módulo: OK**, 2,794 s incluindo carregamento. Total: **765 testes backend em 58 módulos**, em dois runners. O fornecedor global é usado explicitamente como perfis locais distintos por empresa; duas entradas de 0,01 e 10,02 permanecem individuais apesar do modo diário das saídas. Prévia/repetição/Contribuições preservam todos os registros; outra empresa contabiliza seu próprio perfil. Saídas diárias produzem um agregado de 10,03; consultas de Contribuições preservam origens antes/depois de estorno parcial de 0,01, com balanço e FK íntegros.
- **184 testes frontend: OK**, 3,118 s. **Build Vite dev.29: OK**, 4,63 s; bundle 848,71 kB, gzip 251,34 kB, mantendo o aviso existente de tamanho acima de 500 kB. Dependências diferem somente pelas alterações recebidas de develop. Não há lint separado configurado.
- **Quatro roteiros Chromium 151: OK**, **27 grupos**: integração=7, Prosoft=10, contexto=6, totalizadores fiscais=4, zero erros JavaScript. Preservados ambos os acessos, repetição após perda de resposta sem duplicidade, interrupção/prévia, filtros, isolamento, dados anteriores, mapeamentos e exportações Prosoft. O cenário de navegação Prosoft continua sob 750 ms de latência real via CDP.
- Paridade de versões, sintaxe Python do teste novo, compilação Vue e `git diff --check` no trabalho/index: OK.

### Smoke geral local incompleto

O smoke geral **não foi contado como aprovado**. Com Chromium headless shell 151 completou 14 verificações, incluindo os dois grupos de criação/edição/cancelamento/desativação/uso de Terceiros e Contadores do helper original, e terminou em timeout de `popup.wait_for_load_state('domcontentloaded')` na prévia PDF de `browser_exports.py`. A tentativa de repetir o smoke inalterado com Chromium completo 151 não iniciou: o ambiente recusou `socket()` do process singleton (`Operation not permitted`, SIGABRT). Não foi acrescentado skip, alterado timeout, removido assert ou aplicado contorno ao smoke. A execução direta do helper de Cadastros não é um teste standalone e não foi contada como validação; os checks de UI de Cadastros efetivamente observados vieram do smoke.

A restrição local fica explícita para revisão; o novo CI deve executar seu gate geral completo em ambiente próprio. O roteiro Prosoft que falhara anteriormente está preservado e passou na árvore composta; o antigo sucesso de CI não substitui a nova execução.

[Resultados e hashes sintéticos](evidence/pr49-dev29-composition.json). Os comandos usam `TMPDIR` isolado na pasta ignorada da worktree e `ESCRITURA_DATA_DIR` temporário/`ESCRITURA_DEMO=0` antes da importação da aplicação. Navegadores executam servidores locais/SQLite descartáveis e Playwright 1.62/Chromium 151 isolados; nenhum dado de instalação real é usado. Os relatórios de contexto podem registrar o head anterior durante o merge ainda não commitado; os hashes identificam a fonte efetivamente testada.

Não executados suíte integral local, PostgreSQL operacional, instaladores/imagens, homologação Prosoft/PVA ou escala. Os testes de infraestrutura simulam seus artefatos/serviços; nenhuma implantação real é operada. A integração segue parcial: importação automática, distribuição por itens/classificações e ligação dos botões individuais anteriores continuam pendentes e avisadas na tela. Sem dados reais, backups de usuário, logs privados, produção, merge final, release estável ou deploy. Trabalho local anterior preservado.
