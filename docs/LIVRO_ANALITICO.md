# Livro auxiliar analítico de entradas e saídas

Os relatórios `fiscal-entries` e `fiscal-outputs` selecionam documentos escriturados pela data de escrituração e apresentam linhas do motor `fiscal_posting_lines`. O contrato `row_scope=analytical_posting_lines`, versão 1, distingue:

- `document_headers`: identidade e total integral de cada documento, uma única vez.
- `rows`: parcelas contábeis por CFOP, CST/CSOSN, origem, alíquota e tratamento. `total_cents` é a parcela, não uma cópia do total documental.
- `totals.documents` e `totals.lines`: contagens distintas; `document_total_cents` é referência dos documentos completos, enquanto `total_cents` soma as linhas selecionadas.
- `book_*_cents`: base, ICMS, IPI e Outras do livro. Ausência de decisão fiscal fica nula, sem presunção automática de crédito ou de Outras pelo regime da empresa.
- `declared_*_cents`: valores declarados na fonte, separados dos valores de livro. `ipi_allocated_cents` é o componente econômico de IPI alocado pelo motor; sem declaração identificável, IPI declarado permanece nulo mesmo se o componente econômico é zero.
- `source_kind`, `item_numbers`, `ncms`, `treatment` e `pending`: rastreabilidade da linha. Totais conhecidos têm contagem de cobertura; nenhum valor conhecido resulta em total nulo, não zero presumido.

O filtro CFOP seleciona somente as linhas correspondentes. O filtro NCM seleciona linhas fiscais inteiras que contêm aquele NCM: uma linha pode conter outros NCMs e não é fracionada novamente. Os cabeçalhos continuam documentais e seu total não deve ser confundido com o subtotal filtrado.

PDF e Excel usam o mesmo resultado da consulta. O PDF tem cabeçalhos, livro analítico, valores declarados, rastreabilidade e cobertura. O Excel acrescenta a aba `Cabeçalhos documentos` e preserva `Dados` e `Valores em centavos`. Os relatórios operacionais de documentos, itens e tributos continuam com seu escopo original; não foram convertidos implicitamente em livros analíticos. Os formatos disponíveis continuam PDF e XLSX.

Os perfis fiscais são explícitos e não equivalem à validação legal da incidência ou crédito. O perfil `other_excluding_ipi` separa valor contábil, IPI destacado e Outras, mas não deve ser aplicado universalmente a optantes pelo Simples. O módulo não afirma homologação visual ou equivalência integral a sistema de terceiro. Divergências entre a agregação analítica e um livro de referência exigem conferência da parametrização e das fontes.

## Validação sintética

`tests/test_fiscal_analytical_reports.py` cobre combinação de classificações, origem/alíquota na mesma CFOP, soma das parcelas sem duplicar a nota, filtros CFOP/NCM, movimento, valores desconhecidos, estorno, manutenção do relatório documental e exportação PDF/Excel. A suíte usa somente documentos fictícios. Nenhuma fonte empresarial real integra estes testes ou este documento.

## Agrupamento revisado

`posting_group_review` registra o modo `split` ou `consolidate`, o mapa completo dos itens, fonte, responsável e motivo. Os relatórios apresentam essa decisão, `posting_group`, `grouping_mode` e `declared_classifications` completos em JSON/Excel e na seção de grupos revisados do PDF. Na consolidação autorizada, alíquota, origem ou CST heterogêneos ficam nulos na coluna comum: suas classificações permanecem no detalhamento, sem inventar alíquota zero ou descartar diferenças. O teste sintético de consolidação verifica duas alíquotas/origens/CSTs, uma única linha, conservação dos valores e recuperação integral das classificações no Excel e PDF.

A aba Excel `Classificações declaradas` oferece uma classificação por registro, sem depender do limite de caracteres de uma célula. Caso a lista exceda esse limite, a célula de resumo aponta para essa aba, em vez de truncar silenciosamente. Os campos `declared_tax_coverage` e `declared_tax_partial_totals` preservam a cobertura e os subtotais informados pelo motor; um agregado incompleto permanece nulo nas colunas de totais declarados.
