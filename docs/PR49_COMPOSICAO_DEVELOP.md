# PR49 — composição com develop dev.23 após PR40/PR44

## Referências e escopo

A atualização sincroniza somente a branch da PR49, `feat/fiscal-accounting-incoming-20261116`, por merge sem rebase/force push. O trabalho anterior permanece em sua worktree; a composição foi feita em outra worktree a partir do head público exato.

| Referência | SHA/estado |
| --- | --- |
| Head público original da PR49 | `1ea10406a8a1c3cfcbade8ddb1ff34d7a3b66baf` |
| CI anterior da PR49 | [43801774632](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43801774632), concluído com sucesso |
| **develop composta e testada** | **`67a5e2e0b3c65fe7948827d6d66da5361970bfb1`**, `0.9.0-dev.23` |
| PR40 já integrada | `4204eae` |
| PR44 já integrada | `85bfd34`, head `551fdde8f82be702a1d73e5cedc4ced3ca0ad630` |
| Workflow de publicação observado | [43812084887](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43812084887), independente do CI desta atualização |

O primeiro pai do merge de atualização é o head original; o segundo é a develop acima. A publicação confere o head remoto esperado, sem forçar a referência. Nenhuma branch paralela ou develop recebe gravação. Não há `AGENTS.md`/`.agents/skills` no checkout. O merge final da PR permanece reservado à coordenação posterior, inclusive quanto ao workflow de publicação; esta atualização não executa merge final, release ou implantação.

## Composição e preservação

O merge foi automático e sem conflitos. Os dois arquivos com mudanças das duas frentes foram conferidos:

- `frontend/src/App.vue` conserva **Fiscal → Integração Contábil** e **Contábil → Integração Fiscal**, no mesmo componente/processo, acrescentando somente o menu de exportação Prosoft fiscal recebido de develop.
- `app/permissions.py` conserva as regras de leitura/execução de entradas e saídas e recebe as regras Prosoft da develop. A prévia da integração permanece leitura; gerar exige criação e as demais permissões de domínio.
- Serviço, tela, teste Vue, roteiro Chromium e testes de entradas da PR49 permanecem byte a byte iguais ao head público original. Entradas continuam individuais; saídas mantêm individual/consolidação diária opcional, com seleção explícita de modelos/contas, competência de escrituração, fechamento, rastreabilidade e idempotência.
- Serviços Prosoft, mapeamentos por empresa, SPED, core/API, consultas otimizadas e dashboard são idênticos à develop testada. O workflow de CI também é idêntico à develop; seus testes existentes descobrem os novos checks automaticamente.

Foram acrescentadas duas provas sintéticas de compatibilidade em `test_fiscal_accounting_prosoft_composition.py`, sem mudar código de domínio: persistência independente dos mapeamentos Prosoft fiscal/contábil e da configuração contábil; entradas individuais e saídas diárias; exportação real de arquivos sintéticos balanceados com referências longas rastreáveis; repetição sem nova gravação; exportação em competência fechada preservando a recusa de novas contabilizações; reabertura e estorno rastreável pela nota. Hashes econômicos permanecem iguais nas consultas/exportações. Não houve homologação em Prosoft/PVA nem contato com destino externo.

Os resultados e hashes estão em [evidence/pr49-develop-composition.json](evidence/pr49-develop-composition.json). Evidências anteriores de dev.21 permanecem históricas. O `source_sha` do roteiro de contexto registra o head original durante o merge ainda não commitado; os hashes desta evidência identificam os arquivos efetivamente testados.

## Resultados na composição

- **673 testes backend/infraestrutura em 49 módulos: OK**, sem falhas, erros ou skips; **311,547 s** incluindo carregamento. Incluem a integração individual/diária, idempotência, reprocessamento, estornos, planos globais/próprios, permissões, consultas otimizadas, SPED e os testes Prosoft recebidos de develop, além das duas provas novas.
- **181 testes frontend: OK**, 2,476 s, incluindo contexto, repetição, cancelamento de prévia, filtros e modelos da integração e dos mapeamentos Prosoft.
- **Build Vite dev.23: OK**, 3,67 s. Bundle principal 839,78 kB, gzip 249,28 kB; permanece o aviso de tamanho acima de 500 kB já existente. Não há lint separado configurado.
- **Quatro roteiros Chromium 141: OK**, **26 grupos** (integração=7, Prosoft=9, contexto=6, totalizadores fiscais=4), zero erros JavaScript. Entradas de 0,01 e 10,02 ficam individuais mesmo com saídas diárias; saídas de mesmos valores geram um agregado de 10,03. Interrupção de resposta após commit e repetição exata preservam hashes; alternar menus não duplica lançamentos. Prévia/fechamento, consultas e exportações preservam dados econômicos. Mapeamentos, layouts e configurações permanecem por empresa; respostas antigas são descartadas. Balanço/FK e movimentos anteriores permanecem íntegros.
- **127 arquivos backend conferidos contra develop**: somente serviço e permissões originais da PR49 diferem. Os cinco blobs de serviço/tela/testes/roteiro da integração são idênticos ao head público anterior. Sintaxe Python, compilação Vue, paridade de versões e `git diff --check` no trabalho/index: OK.

Comandos principais: `npm ci --ignore-scripts`, `npm run build` e `node --test tests/*.test.js` em frontend; runner `unittest` dos 49 módulos listados na evidência, com `ESCRITURA_DATA_DIR`/`ESCRITURA_DEMO` definidos antes de importar a aplicação; `scripts/browser_fiscal_sales_accounting.py`, `scripts/browser_prosoft_export.py`, `scripts/browser_workspace_context.py` e `scripts/browser_document_summary.py`. Todos os comandos válidos usam `TMPDIR` isolado na worktree. Dependências DANFE/Playwright/Chromium são as instalações isoladas de teste já disponíveis.

## Ambiente e limites

`/tmp` estava sem espaço e as primeiras tentativas encerraram antes de produzir resultados válidos. Elas não foram contabilizadas como sucesso. Os checks válidos usam `TMPDIR` em uma pasta ignorada da worktree; nenhum arquivo de outra tarefa foi apagado. A aplicação global só é importada depois de definir `ESCRITURA_DATA_DIR` temporário e `ESCRITURA_DEMO=0`. Navegadores usam aplicação local/SQLite descartável e Playwright/Chromium de teste já isolados; nenhum dado de instalação real é acessado.

A integração continua parcial: importação automática, distribuição por itens/classificações e ligação dos botões individuais anteriores seguem pendentes, conforme aviso da tela. O Diário Consolidado permanece somente leitura e independente da geração. Não foram executados suíte integral do repositório, PostgreSQL operacional, instaladores/imagens, escala ou homologação em destino. O novo CI precisa ser avaliado no SHA publicado; o CI anterior verde não substitui seus checks. Sem dados reais, backups, logs privados, produção, merge final, release estável ou deploy.
