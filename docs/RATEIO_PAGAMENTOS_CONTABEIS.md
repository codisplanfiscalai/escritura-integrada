# Rateio contábil nativo por meios de pagamento

Base original da PR68: `develop` em `2a80b87ce2e2666013dff54dfe678e66a90b54e2`, `0.9.0-dev.41`. PR64 e PR50 já incorporadas; nenhuma alteração em SPED, relatórios, importadores ou workflows.

## Comportamento anterior e incremento

A integração permitia um débito e um crédito pelo total de cada nota, ou um modelo opcional. As contribuições por documento já eram preservadas na auditoria, com geração atômica, idempotência e estorno pela origem. A nova opção **Contas por meios de pagamento declarados** reaproveita esses serviços e vínculos; não usa CSV nem cria lançamentos soltos.

Na subguia Contabilizar, selecione a forma de débito e informe uma conta para cada meio declarado e a conta de crédito do total. Nenhuma conta vem preenchida. O nome exibido para dinheiro/cartão apenas identifica o código fiscal; não escolhe a classificação contábil. Centro de custo e participante continuam sujeitos às regras das contas da empresa e do plano selecionado. A seleção de modelo opcional retorna ao débito único, sem misturar métodos na mesma nota.

A consulta dos pagamentos ocorre somente ao optar pelo rateio ou mudar sua seleção. É cancelável e descarta respostas antigas após troca de empresa, exercício, sentido, seleção ou fechamento da tela. Alternar subguias preserva contas, troco e seleção, sem consulta adicional. A consulta detalhada por nota é expansível e só monta suas linhas ao abrir; contas e troco ficam visíveis.

Atualização de compatibilidade: [notas antigas sem snapshot podem recuperar pagamentos do XML original íntegro e correspondente](PAGAMENTOS_XML_LEGADO.md), somente em memória e sem alterar a revisão.

## Evidência e valores

O servidor lê `declared_document_fields/pag/detPag` preservado pelo importador, com `tPag`, `vPag`, descrição opcional e `pag/vTroco`. Aceita este rateio para saídas NF-e/NFC-e 55/65. Não reconstrói pagamentos de tributos, CFOP, descrições livres ou total da nota.

Os valores são centavos inteiros, calculados no servidor. A soma de pagamentos menos o troco precisa corresponder ao total escriturado. Cada detalhe continua identificado pelo índice original, mesmo com meios repetidos. Troco não é atribuído automaticamente a dinheiro: o operador distribui explicitamente seus centavos entre os detalhes, sem exceder o valor de cada um. Pagamento totalmente devolvido em troco fica na evidência com líquido zero, sem partida zero no diário.

Ausência, ambiguidade ou divergência de pagamentos é mostrada por nota na consulta. A prévia/execução revalida e recusa rateio inconsistente sem gravação parcial. Notas sem evidência podem continuar usando o fluxo anterior de contas diretas/modelo. Valores de sem pagamento/pagamento posterior (90/91) não são transformados em movimento por este rateio. Isto não constitui validação XML/XSD ou homologação fiscal completa.

Referências primárias: [MOC mantido pela SEFAZ/PR, regras YA03 e YA09](https://moc.sped.fazenda.pr.gov.br/NFe_NFCe/NFe_NFCe/RegrasDeValida%C3%A7%C3%A3o.html), sobre pagamentos/troco; [MOC 6, página 224, nomes dos códigos históricos 01/03/04](https://portal.fazenda.sp.gov.br/_layouts/download.aspx?SourceUrl=/servicos/nfce/Downloads/Manual_de_Orientacao_Contribuinte_v_6.pdf). O código usa a estrutura detPag preservada no produto e não tenta implementar todas as regras fiscais dessas referências.

## Consolidação e preservação

Individual continua sendo um lançamento por nota, agora com tantos débitos positivos quanto os pagamentos efetivos. No modo diário, notas com dinheiro e notas mistas podem compartilhar o lançamento se tiverem mesma data de escrituração, classificação, mapeamento explícito de meios/contas, crédito, centro e dimensões de participante. A UI envia o mesmo mapeamento completo da seleção para todas as notas. Mapeamentos/classificações/datas diferentes permanecem separados; a emissão não substitui a competência.

A auditoria de cada nota registra `entry_method=payments`, `payment_snapshot` (bruto, troco, líquido, índice, meio e referência escolhida), partidas normalizadas e vínculo do diário. Rastreabilidade e estorno continuam pelos serviços existentes: estornar uma origem compartilhada compensa apenas suas próprias partidas, sem reescrever as demais notas ou o lançamento original.

A operação usa a transação e chave de idempotência existentes. Repetir a mesma solicitação retorna o resultado anterior; uma chave nova ou mudança de modo não recria notas já vinculadas. Concorrência, inclusive com chaves diferentes, tem um único efeito. Lançamentos antigos não são remodelados. Competência fechada exige reabertura. Planos globais virtuais são resolvidos pela API de contas existente e a prévia não os materializa.

O endpoint POST `fiscal-sales-accounting/payments` é uma consulta de evidência por IDs/versões, exige leitura fiscal e de contas e não exige criação de diário. Geração exige a permissão existente de criação contábil; prévia exige leitura de diário. Isolamento de empresa, exercício, CSRF e permissões da sessão permanecem ativos.

## Testes sintéticos

[Evidência estruturada](evidence/fiscal-payment-allocations.json) inclui resultados e hashes das fontes. Não foram utilizados XMLs, backups ou dados reais.

- 209 testes frontend aprovados, incluindo captura imutável de payload, cancelamento/resposta atrasada, troca de empresa, troco e retorno ao modelo opcional; build Vite aprovado (aviso de chunk >500 kB permanece).
- 91 testes backend aprovados em oito módulos: 11 novos de rateio, 71 regressões de saídas/entradas/contas diretas/contexto/composição e nove da prévia documental da base dev.41. Cobrem individual/diário, múltiplas datas/classificações/contas/empresas, centavos, meios repetidos, troco distribuído/inteiro, ausência/dados inválidos, permissões, plano global, centro de custo, conta inativa, concorrência, repetição, troca de modo, fechamento/reabertura e estorno parcial.
- Chromium 151.0.7922.34: 12 grupos aprovados, zero erros JavaScript. Preserva os 11 grupos anteriores e acrescenta três notas sintéticas (0,01 + 10,02 + 7,00 = 17,03), com dinheiro/cartão e troco, em um único diário equilibrado com três linhas e três origens. Prévia/cancelamento não alteram hashes; resposta perdida após commit e replay não duplicam. Contas/troco permanecem nas subguias; controles sem extravasamento em 390 px. Capturas sintéticas desktop/mobile inspecionadas localmente.
- Dependências declaradas, versão, compilação Python e whitespace conferidos. Não há comando lint separado no frontend. As tentativas iniciais de navegador encontraram dois erros de montagem da fixture (dígito da empresa e catálogo sem reload); corrigidos sem remover verificações e preservados nos artefatos locais.

Reprodução: instalar dependências de teste do projeto, definir `ESCRITURA_DATA_DIR` descartável e `ESCRITURA_DEMO=0` antes de carregar a API; `PYTHONPATH=tests:scripts:. python -m unittest test_fiscal_payment_allocations test_fiscal_sales_accounting test_fiscal_incoming_accounting test_direct_fiscal_accounting test_fiscal_sales_composition test_fiscal_accounting_prosoft_composition test_workspace_context test_document_preview`. Interface: `node --test frontend/tests/*.test.js`, `npm --prefix frontend run build` e `python scripts/browser_fiscal_sales_accounting.py` (aceita `ESCRITURA_TEST_BROWSER`). O roteiro cria seu próprio servidor/banco temporário de demonstração.

## Limites e próximo incremento

Este incremento não contabiliza na importação nem aplica dados na instância real. Entradas continuam individuais no fluxo anterior; não há rateio de créditos, itens/tributos, taxas de cartão, recebimento, baixa, conciliação financeira, criação de títulos ou inferência de saldo/conta/classificação. Não altera o Diário Consolidado, que continua somente leitura. Documentos sem pagamentos reconciliados no snapshot nem no original correspondente precisam de conferência ou do fluxo anterior.

Mapeamentos são explícitos para a seleção atual e são limpos ao trocar contexto; não há persistência automática de novas contas padrão por empresa. Um próximo incremento pode oferecer configuração de meios por empresa, se solicitada, sem aplicar retroativamente ao histórico. Suíte backend integral, PostgreSQL, Qt empacotado, Windows/macOS e escala de produção não executados localmente. CI do head publicado deve ser verificada separadamente. Sem merge, release ou implantação nesta entrega.
