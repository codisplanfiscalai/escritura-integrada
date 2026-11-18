# Balancete: hierarquia, movimento e impressão compacta

Comparação com o balancete de referência fornecido pelo usuário: retrato, tipografia monoespaçada, acesso/classificador, sintéticas destacadas e recuo das analíticas, cabeçalho empresarial/período/folha e quatro valores por conta. Não declara reprodução pixel a pixel nem homologação externa.

O PDF antigo fornecido tinha 4.804 páginas: plano integral com contas zeradas e anexo técnico por registro. O balancete normal passa a imprimir somente os campos contábeis; IDs e origens continuam disponíveis no resultado/Excel/CSV e detalhes, sem anexo técnico obrigatório por conta. Outros relatórios não mudam.

## Filtro e valores
- `Com movimento` é o padrão, independente de Conta: Todas ou seleção específica.
- A ajuda explica que saldos anteriores/finais são preservados mesmo sem débitos/créditos no período. A referência também conserva contas nessa condição.
- `Todas as contas` é opção explícita. O padrão só omite contas com todos os quatro valores zero; os totais não mudam.
- Sintéticas existentes são restauradas como subtotais dos descendentes, sem criar contas ou alterar dados. Selecionar sintética abrange suas analíticas.
- Totais são exclusivamente analíticos, nunca somam os subtotais novamente. Analíticas com mesmo classificador continuam distintas por ID/acesso.
- Hierarquia usa segmentos do classificador; somente grupos finais inteiramente zero são padding em classificadores pontuados. Classificadores legados compactos usam padding de zeros final. Não corrige o plano nem presume contas faltantes.
- Período, empresa, centro e permissão permanecem no caminho normal. Consulta e impressão são somente leitura.

## Limites de validação
Testes usam bancos/contas/partidas sintéticos. Nenhuma correção de saldos reais, reclassificação ou implantação. PDF sintético renderizado e inspecionado; modelo retrato compacto sem zebra/anexos internos. Navegador local bloqueado antes do lançamento por `socket() failed: Operation not permitted`; cenário de filtro acrescido ao roteiro Chromium existente para CI, sem contornar o bloqueio.

## Resultados locais
- Regressão de domínio/API, modelos, plano global, ECD e Razão: 89 testes aprovados.
- Após ajustes finais de rastreabilidade/chunk e caso de classificador repetido: 23 testes dirigidos aprovados.
- Frontend: 238 testes aprovados; build Vite aprovado (aviso preexistente de chunk >500 kB).
- Caso de 20.000 contas zeradas: padrão retorna zero linhas; mudança para todas é explícita.
- Sintaxe e diff-check aprovados. PDF final de fixture sintética renderizado e inspecionado.
- Chromium não executado até a UI por bloqueio do executor; aprovação visual UI segue pendente no CI.

## Evolução: seleção múltipla e barra de filtros
- Conta(s) e Movimento ficam na barra principal, com disposição responsiva; demais opções de impressão continuam recolhíveis.
- Busca por acesso/classificador/nome, checkboxes, seleção preservada durante busca, chips removíveis, ESC/Concluir e limpar para Todas as contas. Limite explícito de 500 seleções; catálogo pesquisável em janelas de 200 opções.
- União validada por empresa em balancete, Diário, Razão, Diário consolidado, centros de custo, Balanço e DRE. Sintética + descendente e seleções repetidas não duplicam partidas. Filtros capturados são usados igualmente na visualização e PDF/Excel/CSV.
- Classificadores compactos e pontuados são reconciliados somente por máscara explicitamente salva no plano local/compartilhado. Não é inferida uma máscara a partir dos números nem afirmada ocorrência em dados reais.
- Testes acrescentados: união, grupos sobrepostos, limites, sintaxe inválida, conta estrangeira, formatos, múltiplos relatórios e máscara mista explícita. Roteiro Chromium cobre busca sem correspondência preservando seleção, movimento independente, ESC e limpar.
- Validação da evolução: 85 testes backend de regressão aprovados; após reforço de paridade CSV/Excel, 10 testes específicos aprovados. Frontend final 239 testes e build aprovados. Navegador permanece sujeito ao CI.
