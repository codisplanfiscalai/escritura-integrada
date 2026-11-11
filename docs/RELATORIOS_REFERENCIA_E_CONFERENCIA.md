# Relatórios de referência e conferência da escrituração

## Fluxo operacional

A consulta apresenta documentos, linhas e valores com rótulos de operação. A grade não expõe objetos de implementação. **Ver detalhes** conserva as classificações, coberturas, grupos revisados e origem; CSV e Excel mantêm os dados completos da seleção.

**Escriturado** é o estado do documento. Isso não confirma, por si só, tratamento tributário nem crédito. Um documento pode estar escriturado e ainda ter linhas fiscais a revisar. O livro informa quantas linhas e quantos documentos estão nessa situação. Campos não informados ficam em branco, sem serem convertidos em zero. Uma soma com cobertura incompleta é identificada como parcial.

O botão **Ver pendências de conferência** abre a mesma seleção efetivamente gerada, mesmo que os controles tenham sido alterados depois. A consulta de pendências reúne a mesma crítica por documento e indica as linhas afetadas. Assim, quatro documentos com cinco linhas sem tratamento representam quatro ocorrências dessa crítica, não cinco notas distintas nem documentos não escriturados.

Para concluir os valores do livro, confira o documento e revise o tratamento no fluxo de escrituração/reprocessamento, com fonte, responsável e vigência. O relatório não escolhe crédito, Outras, isenção, IPI ou partições por conta própria.

## Modelos e compatibilidade

As alternativas genéricas substituídas foram retiradas da seleção. Razão usa o seu modelo de referência; entradas e saídas usam P1/A/P2/A. Os demais relatórios com modelo específico usam esse modelo, sem uma segunda alternativa genérica. Relatórios funcionais sem substituto comprovado não foram eliminados.

URLs anteriores com `model=internal`, ou com os antigos modelos auxiliares de entradas/saídas, continuam válidas. O servidor resolve o modelo específico disponível. Dados, filtros, permissões, origem e exportação CSV/Excel permanecem acessíveis.

A ausência de exemplar equivalente para uma variante continua registrada no catálogo. Nomear um relatório ou reproduzir os campos de um formulário não comprova identidade com a Prosoft.

## Avanços comprovados nos livros

- Observação **IPI não creditado** na mesma parcela, somente com IPI declarado conhecido e completo, decisão explícita de Outras sem crédito e IPI do livro zero. Não é deduzida da diferença entre valor contábil e Outras.
- Resumo CFOP com grupos, descrição cadastrada, subtotal e total. Somam-se as parcelas analíticas, nunca cabeçalhos repetidos. Redação de catálogo fora da vigência não é aplicada ao período.
- Pendências impressas em português operacional; os códigos continuam estruturados na API/exportação.

## Lacunas mantidas explícitas

- Divisões de entradas precisam da relação item → grupo ou de critério revisado. Coincidência de valores não prova uma partição.
- Código contábil não é uma constante por CFOP. Sem mapeamento efetivo, o campo fica em branco.
- Os anexos UF/contribuinte de saídas fornecidos têm escopo limitado. Não há evidência para somar todas as saídas, nem para inferir contribuinte somente pela presença de IE.
- O resumo de observações exige associação explícita às parcelas; não equivale a agrupar um CFOP inteiro.
- Densidade, quebras e variantes sem exemplares equivalentes continuam pendentes de validação. Não houve declaração de homologação total, cálculo legal automático ou aceite de intercâmbio no programa Prosoft.
