# Roteiro de teste da importação fiscal

Use este roteiro em uma base de homologação com backup, nunca como primeiro teste na base operacional. Confira a versão e a revisão do instalador informado junto ao resultado da CI. As referências empresariais usadas nas conferências privadas não acompanham o programa.

## Preparar a empresa e a origem

1. Selecione a empresa e o exercício fiscal corretos. Um XML de outra empresa continua sendo recusado.
2. Abra **Fiscal → Importações fiscais** e selecione um XML ou pacote compatível. PDFs acessórios reconhecidos dentro do pacote são ignorados e aparecem no diagnóstico; os documentos fiscais continuam sendo lidos. Proteções de integridade e de compactação permanecem ativas.
3. Clique em **Analisar e gerar prévia**. Leia os impedimentos e avisos antes de selecionar documentos. Eventos, XMLs sem autorização verificável e XMLs de homologação não devem ser tratados como autorização de produção.
4. Se faltar classificação, confira **Fiscal → CFOP e associações → Associações de importação**. Regras específicas prevalecem sobre padrões contextuais. Informe a destinação correta da compra; revenda não deve ser presumida para uso, consumo, ativo ou operações especiais.

## Conferir as três datas e a classificação

- **Emissão** conserva a data do documento original.
- **Entrada efetiva da mercadoria** é informada pelo usuário. A saída do fornecedor no XML não comprova essa chegada.
- **Escrituração ou competência** determina onde a nota será escriturada, respeitando os bloqueios.

Uma nota emitida em agosto pode ter entrada e escrituração em setembro quando isso corresponder aos fatos. Não altere a emissão para obter esse resultado. A opção **Usar entrada como data de escrituração** copia a data somente quando escolhida expressamente.

Confira CFOP, destinação e itens. A origem e a regra aplicada permanecem identificadas. Em notas com mais de um CFOP, confira as linhas analíticas, incluindo CST/CSOSN, origem, alíquota e tratamento. Deve existir uma nota com parcelas analíticas, sem repetir o total da nota em cada linha.

Quando houver totalizadores divergentes ou tratamento fiscal específico, registre apenas decisões fundamentadas, com fonte, responsável e motivo. Uma decisão sobre vNF não valida protocolo, assinatura, XSD ou tratamento legal RTC. O perfil de Outras descontando IPI não é uma regra universal.

**Visualizar DANFE** abre uma representação do XML original. Confira os valores e feche a prévia para continuar; essa visualização não cria movimentos nem certifica autorização fiscal.

## Conferir faturas e contas a pagar

A seção **Cobrança declarada no XML** apresenta FAT e cada DUP, incluindo número, vencimento e valor. Vencimento não é pagamento.

- Para criar títulos das DUP válidas, marque **Gerar contas a pagar das parcelas do XML**. A opção começa desligada. Confira todas as parcelas antes de confirmar.
- Ausência de cobrança não é erro e não cria parcela presumida.
- Para compras sem cobrança, existe a opção separada **Gerar uma parcela por compra sem cobrança no XML**. Selecione notas ou CNPJs, escolha explicitamente emissão ou entrada efetiva como base, confira o prazo e preencha responsável e motivo.
- O prazo inicial é 30 dias e pode ser ajustado. Valor e vencimento também podem ser revisados com justificativa.
- Base por entrada sem chegada informada deve bloquear a geração, sem usar emissão ou competência como substituto silencioso.
- Cobrança original, inclusive incompleta, não é substituída pelo gerador alternativo. Operações que não sejam compras reconhecidas exigem revisão própria.

As opções criam títulos em aberto. Não executam baixa, pagamento, conciliação bancária ou contabilização. Editar a chegada posteriormente não deve mudar os vencimentos existentes silenciosamente.

## Validar e confirmar

1. Clique em **Validar revisão e selecionar aptos** depois das alterações. Uma mudança posterior deve invalidar a preparação.
2. Confira os documentos selecionados, as linhas e as parcelas propostas. Documentos bloqueados precisam ser resolvidos ou retirados da seleção.
3. Abra a confirmação e use **Voltar** uma vez para cancelar. As datas, classificações e opções revisadas devem continuar na tela.
4. Confirme somente a seleção desejada. Abra a escrituração e as contas a pagar para conferir IDs, valores, vínculos e parcelas.
5. Reimporte o mesmo XML em um teste controlado. Deve continuar existindo um documento por identidade na empresa, sem repetir títulos. Versões realmente divergentes exigem conferência, não outro lançamento silencioso.

## Corrigir depois sem excluir

Em **Escrituração e documentos**, a edição preserva origem e histórico. Emissão, entrada efetiva e escrituração continuam separadas. Períodos fechados exigem reabertura; apurações finalizadas e efeitos vinculados incompatíveis têm seus próprios controles. Corrigir somente a chegada efetiva não deve reescrever títulos ou partidas.

No lote confirmado, use **Revisar / reprocessar existentes**, confira o antes e depois, selecione documentos e informe o motivo. Esse fluxo conserva IDs, valores e fontes; não precisa excluir e reimportar para aplicar uma revisão compatível. Títulos alterados, baixados ou renegociados não devem ser recriados automaticamente.

O controle de pacotes é separado dos movimentos. Arquivar histórico não libera os bytes do original. Remover originais exige os controles apresentados e pode ser impedido quando a fonte é evidência única. A limpeza manual ou periódica nunca deve remover documentos, títulos, partidas ou outros movimentos gerados.

## Registrar o resultado

Anote a versão, empresa de teste, pacote e o passo em que houve diferença. Compare a quantidade de notas, a soma das linhas, FAT/DUP, emissão, chegada, competência e IDs antes e depois. Registre somente o necessário para reproduzir o problema; não publique XMLs, bancos ou dados reais em issues públicas.

Veja também [comportamento e limites da importação](CORRECAO_IMPORTACAO_0_8.md), [livro analítico](LIVRO_ANALITICO.md), [terceiros globais](TERCEIROS_GLOBAIS.md) e [tabelas e padrões fiscais globais](BIBLIOTECA_FISCAL_GLOBAL.md). Esses roteiros não afirmam homologação integral ou equivalência automática com livros de outro sistema.
