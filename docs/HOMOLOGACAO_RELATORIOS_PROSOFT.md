# Roteiro de homologação por relatório

## Estado e regra de conclusão

Este roteiro prepara a homologação; não declara equivalência com a Prosoft. Os testes de aplicação e os builds não substituem a conferência de cada variante com a mesma base, parâmetros e versão do sistema de referência.

Trate separadamente quatro dimensões: **valores, filtros, agrupamentos e visual**. Uma dimensão aprovada não aprova as demais. Uma contagem de linhas igual também não demonstra identidade: uma linha ausente pode ser compensada por um desdobramento adicional em outro documento.

Os arquivos reais e resultados privados da conferência ficam fora do repositório. Use somente bases descartáveis; não publique documentos, nomes, chaves, contas, movimentos ou totais de clientes em fixtures, logs de CI ou capturas de tela.

## Preparar uma sessão comparável

1. Registre commit/árvore do Escritura e versão da Prosoft, empresa, exercício, período, modelo, folha inicial, ordem e todos os filtros. Guarde os hashes das fontes e saídas no dossiê privado.
2. Confirme identidade da empresa, regime e datas de emissão/entrada/competência. Relatório de vencimentos não é relatório de pagamentos.
3. Registre o que está ausente: XML, evento de cancelamento, CT-e, razão completo, plano, parâmetros, ajustes e saldos anteriores. Ausência de arquivo não comprova erro no livro.
4. Gere ambos os relatórios da mesma amostra e exporte os resultados em PDF e formato estruturado, quando disponível. Preserve dados originais e decisões de revisão separadamente.
5. Compare por identidade e por coluna, depois subtotal/grupo/total. Declare valores ausentes como ausentes; não preencha lacunas com zero nem transfira ICMS documental para crédito/débito do livro sem decisão explícita.
6. Renderize e compare páginas: cabeçalhos, colunas, orientação, escala, fontes, quebras, folhas, transportes, observações e fechamento. Inspecione primeiro, último e pontos de quebra; registre páginas efetivamente vistas.
7. Classifique cada diferença como implementação, parâmetro/decisão revisável, fonte ausente, diferença interna da referência ou variante ainda não implementada. Corrija somente o que a evidência demonstra e repita os testes afetados.
8. Assine o aceite por dimensão com responsável, data e evidência. Sem exemplar equivalente ou decisão necessária, mantenha a dimensão pendente.

## Matriz mínima dos modelos disponíveis

| Modelo | Valores e filtros a confrontar | Agrupamento e visual | Estado inicial |
|---|---|---|---|
| Razão Analítico Individual | Saldo anterior, débitos/créditos, saldo por dia/final; conta, centro, período e pesquisa | Histórico continuado, contrapartidas, D/C, folha inicial e continuação | Comparação monetária histórica; visual parcial. Reexecutar na base candidata. |
| Diário Geral | Partidas balanceadas; data, conta, centro e pesquisa | Ordem, múltiplas contrapartidas, total diário e paginação | Auxiliar; exemplar equivalente ausente. |
| Diário Consolidado | Mesmas partidas e totais do diário | Chave diária/conta/centro; não presumir consolidação entre empresas | Auxiliar; critério e exemplar de cada variante pendentes. |
| Balancete | Saldos anterior/movimento/final; período, contas e pesquisa | Sintéticas/analíticas, redutoras e saldo zero | Auxiliar; opções legadas e exemplar pendentes. |
| Centro de custo | Débitos/créditos por conta e centro; seleção do centro | Partidas versus lançamentos, variantes sintética/analítica/consolidada | Auxiliar; não representa todas as variantes legadas. |
| Balanço patrimonial | Classificação explícita, saldos e igualdade dos grupos | Níveis, redutoras, comparativos, termos e assinaturas | Auxiliar; sem encerramento automático ou consolidação intercompanhias. |
| Demonstração do resultado | Contas classificadas em resultado, sinais e período | Grupos, níveis e comparativos | Auxiliar; exemplar equivalente e critérios pendentes. |
| Documentos fiscais | Um cabeçalho por documento; status, direção e período | CFOP/NCM selecionam documento inteiro, sem rateio presumido | Operacional; não equivale aos livros P1/A e P2/A. |
| Livro auxiliar de entradas | Só escriturados; data de entrada, vNF, IPI e valores do livro separados | Linhas analíticas e desdobramentos revisados; preservar CT-e | Conferir por documento/linha; desenho P1/A não homologado. |
| Livro auxiliar de saídas | Só escriturados; separar vendas, devoluções e valores documentais/livro | Desdobramentos; obter documentos/eventos das canceladas da referência | Conferir linhas por identidade; desenho P2/A não homologado. |
| Itens escriturados | Quantidade, unidade, valor e classificação por item | Filtro de item não deve mudar identidade do documento | Auxiliar; exemplar legado equivalente ausente. |
| Operações por CFOP | Somas por código e direção; período e situação | Conferir escopo documental versus analítico | Auxiliar; não equivale automaticamente ao resumo fiscal legado. |
| Operações por participante | Identidade, direção, contagens e valores | Não unir pessoas por nome nem duplicar documentos | Auxiliar; exemplar legado equivalente ausente. |
| Itens por NCM e CFOP | Quantidades/valores de itens e filtros | NCM, CFOP, unidade e direção; não somar unidades incompatíveis | Auxiliar; exemplar legado equivalente ausente. |
| Bases e tributos declarados | Cobertura por tributo; ausente versus zero | Não confundir declarado com devido/creditável; não somar tributos diferentes | Auxiliar; não é apuração legal. |
| Pendências de conferência | Documento, código, evidência e situação | Uma ocorrência não implica omissão tributária | Operacional; exemplar legado equivalente ausente. |
| Livro auxiliar de apuração | Memórias finalizadas não estornadas; competências inclusivas | Ajustes, crédito anterior e quadros P9 completos exigem origem detalhada | Auxiliar; quadro P9 e apuração legal não homologados. |

## Outras saídas e variantes a incluir no dossiê

- Plano de contas: comparar cada acesso, classificador, propriedade e hierarquia com o arquivo original; classificador repetido não autoriza eliminar conta distinta. Validar importação real na Prosoft separadamente.
- Contas a pagar/receber: distinguir empresa, emissão, vencimento, pagamento, abertos e pagos. Títulos derivados do XML não comprovam quitação. O relatório fornecido pode incluir outras empresas.
- Caixa/conciliação: saldo inicial + movimentos = saldo final; separar banco, conta contábil e aplicação. FITID repetido não basta para deduplicar. Divergência de saldo exige crítica, não ajuste automático.
- Variantes sem cobertura completa: ISS 51/53/56, Mapa Resumo ECF, IVA/UF/CFO, autenticação, IPI por decêndio, ANS, balanço comparativo, termos/assinaturas e consolidações especiais. Os captions recuperados não demonstram seus algoritmos.
- Intercâmbio Prosoft/SPED: validar arquivo, leiaute e aceite no programa de destino. Gerar um arquivo ou PDF não comprova importação aceita, escrituração aprovada ou obrigação transmitida.

## Agrupamentos revisados

A aplicação permite revisão explícita `split` ou `consolidate`, identificando **todos os itens**, fonte, responsável e motivo. Consolidação requer CFOP/tratamento compatíveis e perfil vigente de Outras sem crédito. As classificações declaradas continuam rastreáveis e não se tornam crédito automaticamente.

Consolidar o documento inteiro é verificável quando a referência mostra uma única linha. Para dividir uma linha XML em duas linhas de livro, obtenha a relação item → grupo ou critério confirmado. Não resolva o problema procurando subconjuntos que apenas somem os mesmos valores. Uma reprodução sem a prova da partição permanece pendente.

## Evidências de teste a anexar ao aceite

- Relatório privado por dimensão, com esperado/observado/diferença, identidade, fonte e estado.
- Testes automatizados do commit candidato: domínio/API, exportações, frontend e navegador. Informe o que passou, falhou e não foi executado.
- Amostras visuais das saídas efetivas e suas referências, com páginas inspecionadas.
- Pendências documentais, regras/decisões que ainda dependem de revisão e variantes ausentes.
- Aceite fiscal/contábil e validação Prosoft de intercâmbio, separados dos testes técnicos.

Referências de campos, geometria, fontes e limites: [RELATORIOS_PROSOFT_REFERENCIAS.md](RELATORIOS_PROSOFT_REFERENCIAS.md). Operação dos modelos e filtros: [RELATORIOS_E_MODELOS.md](RELATORIOS_E_MODELOS.md).
