# Contabilização fiscal direta, com modelos opcionais

## Inventário e base

O estado remoto conferido mostra a PR49 já mesclada em `50dd55b`. A develop deste incremento é **`2bc2051486afeba3612b31fb112c32f213328cc9`**, **0.9.0-dev.30**. PR50/52/53/58 estavam abertas em outras frentes; nenhuma de suas branches é modificada. A antiga branch da PR49 e suas worktrees permanecem preservadas. Esta alteração segue em branch/worktree nova a partir dessa develop. Não há `AGENTS.md` nem `.agents/skills` no checkout.

Antes deste incremento, a integração em lote exigia `model_id` para cada nota e leitura de modelos, embora a escrituração individual em `DocumentsView`/`account_document` já aceitasse contas/partidas diretamente. A importação fiscal permite importar/escriturar sem modelo contábil: suas validações de CFOP, competência e dados fiscais pertencem à escrituração fiscal e não são substituídas por contas escolhidas nesta tela. Não foi encontrada obrigação de modelo contábil nesses fluxos individuais/de importação.

## Fluxo entregue

Os dois acessos aprovados continuam apontando à mesma tela/processo: **Fiscal → Integração Contábil** e **Contábil → Integração Fiscal**.

1. Selecione entradas ou saídas já escrituradas e ainda não contabilizadas.
2. Informe **Conta a debitar** e **Conta a creditar** entre as contas analíticas ativas do plano da empresa. Não há escolha automática, conta fictícia, plano fixo 050/DIX, cadastro de modelo ou configuração adicional obrigatória. O seletor existente permite pesquisar planos grandes.
3. Se a conta exigir, informe o centro de custo. Edite o histórico no próprio fluxo se precisar; em branco, permanece a descrição padrão da integração, como antes. O valor vem do total da nota no servidor, sem digitação/cálculo paralelo do total contábil pelo cliente.
4. Consulte a prévia opcional e gere a seleção. A prévia é somente leitura e usa as mesmas validações/partidas da execução.

**Modelos ficam opcionais**, na seção “Usar modelo salvo (opcional)”. É possível aplicá-los à seleção, trocar o modelo de uma nota específica ou voltar a usar as contas diretas. Uma seleção pode conter notas diretas e notas com modelo. Notas diretas usam o par de contas/centro informado para a seleção; a API também aceita um par por nota. O modelo escolhido continua sujeito a autorização, atividade, revisão, sentido e vigência. A ausência de modelos ou de permissão para consultá-los não impede o fluxo direto e não dispara busca de modelos.

Entradas permanecem **individuais**. Saídas conservam a escolha persistida individual/diária. No modo diário, notas compatíveis de qualquer forma de entrada são agrupadas por data de **escrituração**, classificação e contas/dimensões; uma escolha direta e um modelo com as mesmas partidas podem formar um mesmo agregado. A emissão permanece independente. A configuração do modo não muda os lançamentos anteriores.

## Serviço, API e integridade

Os endpoints existentes de prévia/geração para entradas e saídas são estendidos sem migração de dados ou novo processo de contabilização. Cada item de `entries` contém documento/versão e uma das formas:

| Forma | Campos por nota |
| --- | --- |
| Direta | `debit_account_id`, `credit_account_id`, `cost_center_id` opcional |
| Modelo opcional | `model_id` |

As referências de conta são IDs da empresa ou aliases globais disponíveis no plano vinculado; não são códigos presumidos. Não se aceita modelo e contas diretas simultaneamente na mesma nota. Campos desconhecidos, inclusive totais enviados pelo cliente, são recusados. As duas contas devem ser diferentes depois da resolução de aliases. A normalização existente valida conta ativa/analítica, centro obrigatório, participante/fornecedor explícito, débito/crédito e total da nota.

O serviço reutiliza `_document_accounting_lines`, `_normalize_lines`, `_create_journal` e a transação/idempotência existentes. A permissão `accounting.histories:read` só é necessária quando a seleção inclui modelo, inclusive ao repetir uma operação desse tipo. O fluxo direto mantém documentos fiscais e criação/leitura de lançamentos conforme a operação; a UI precisa de leitura das contas e consulta de centros quando usados. Nenhuma permissão de criação/edição de modelos é necessária. Empresa, exercício, sessão, CSRF, competência aberta, versões e limites técnicos permanecem validados.

A prévia não materializa contas globais, cria modelos, títulos, movimentos, vínculos, auditoria ou operação persistida. Na geração, a referência global pode ganhar o alvo técnico FK permitido pelo serviço de contas existente; a UI conserva sua escolha quando esse alias ganha ID operacional. Contas locais/próprias e o histórico anterior permanecem intactos.

As contribuições guardam partidas, valores, nota/versão/hash, classificação e `entry_method` (`direct`/`model`). O snapshot de modelo é nulo nas notas diretas. A tela identifica “Contas informadas diretamente nesta integração” na trilha. Eventos antigos continuam legíveis. Estorno segue pelo documento, usando as contribuições preservadas. Limpeza de lotes não é alterada e não exclui lançamentos.

Troca de empresa/exercício/sentido/permissão limpa contas e seleção; respostas antigas não repovoam outro contexto. Mudar contas, centro, histórico, seleção ou opção de modelo invalida a prévia. Enquanto a mutação está em curso, permanece o controle global de contexto da aplicação. Em resultado incerto, repetir conserva exatamente o endpoint, corpo, contas/modelos, histórico, versões e chave. Novas chaves, troca de modo e reprocessamento não recriam notas já vinculadas. Não há recriação de histórico ao escolher contas diretas.

O Diário Consolidado permanece consulta independente somente leitura, sem alterar lançamentos. Não foram removidas validações fiscais essenciais nem acrescentadas frases, certificações ou confirmações adicionais.

## Importações e escrituração individual

A investigação preservou os caminhos existentes: a escrituração individual já oferece “Definir nesta escrituração” e contas diretas; a importação/escrituração fiscal não exige modelo contábil. Nenhuma alteração foi feita em `DocumentsView` (frente da PR50), `ImportView`, seus serviços ou o roteiro Prosoft compartilhado com a PR52. Notas importadas e escrituradas podem ser selecionadas nesta integração direta.

Aplicar automaticamente a contabilização durante a importação é um incremento separado, ainda pendente. Não foi acrescentado um efeito automático a um fluxo cujo usuário escolheu somente importar/escriturar. Distribuição contábil por itens/classificações, múltiplas partidas/rateio por nota e unificação dos antigos botões individuais com este lote também continuam fora deste incremento. As contas diretas desta tela não persistem como sugestão automática para futuras seleções.

## Validação e limites

- **693 testes backend em 50 módulos: OK**, sem falhas/erros/skips, 383,929 s incluindo carregamento. Incluem nove testes novos de contas diretas e regressões de núcleo, planos locais/globais, permissões, competências, reprocessamento, estorno, consultas otimizadas, Prosoft e SPED.
- **189 testes frontend: OK**, 3,209 s. Cinco testes novos exercitam o componente compilado com contas diretas, ausência de permissão de modelos, centro exigido, mistura opcional, alias materializado, contexto e repetição congelada.
- **Build Vite dev.30: OK**, 5,23 s, bundle principal 851,83 kB/gzip 252,17 kB; o aviso acima de 500 kB permanece. Sem alteração de dependências do produto.
- **Chromium 151/Playwright 1.62: OK**, 18 grupos (integração=8, Prosoft=10), zero erros JavaScript. Empresa A=8/B=2/C=3 lançamentos, balanceados e com integridade FK. A empresa C permanece sem modelos. Prévia, leitura de relatório e repetição após perda de resposta mantêm hashes de documentos/lançamentos/partidas/títulos/auditoria; campos fiscais, título e lançamento anterior foram preservados. O histórico escolhido aparece no lançamento e as contas diretas são identificadas na origem.
- Conferência visual de configuração/contas/histórico e viewport de 1100 px. Sintaxe Python, compilação Vue, paridade de versões e `git diff --check`: OK.

Comandos principais: `npm --prefix frontend ci --ignore-scripts`, `npm --prefix frontend run build`, `node --test frontend/tests/*.test.js`; runner `unittest` dos 50 módulos listados no JSON com `ESCRITURA_DATA_DIR` temporário e `ESCRITURA_DEMO=0` antes de importar a aplicação; `scripts/browser_fiscal_sales_accounting.py` e `scripts/browser_prosoft_export.py` com `TMPDIR` isolado e o navegador/dependências de teste existentes. Os screenshots são gerados em `artifacts/browser-fiscal-sales-accounting/` e o workflow existente os recolhe, sem alteração de CI.

Os resultados exatos, módulos, hashes e relatórios sintéticos ficam em [evidence/direct-fiscal-accounting.json](evidence/direct-fiscal-accounting.json). Os testes novos cobrem notas sem nenhum modelo cadastrado, uso direto sem permissão de modelos, mistura com modelo opcional, centavos, contas/centros inválidos, isolamento entre empresas, referências globais virtuais e plano próprio, troca de modo, fechamento/reabertura, estorno, concorrência, prévia/relatório sem escrita e repetição sem duplicação.

No navegador, a empresa C é criada sem modelos: duas saídas de 0,01 + 10,02 formam um agregado diário de 10,03, e duas entradas de mesmos valores permanecem individuais. Nenhum modelo é criado. O cenário também mantém o uso opcional de modelos nas empresas anteriores, origem/histórico e os hashes nas prévias/repetições. Somente fixtures sintéticas, aplicação local e SQLite descartável; instalação de Playwright/Chromium de testes isolada, sem alterar dependências do produto.

A integração continua parcial nos pontos acima. Não foram executados a suíte integral do repositório, PostgreSQL operacional, instaladores/imagens, homologação Prosoft/PVA, escala ou ambientes reais. Há o aviso já conhecido de bundle acima de 500 kB; não há lint separado configurado. Publicação de PR não é deploy: sem dados reais/backups/logs privados, merge final, release ou implantação. O novo CI deve ser conferido no head publicado.
