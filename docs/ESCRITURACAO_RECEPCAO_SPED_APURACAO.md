# Recepção, escrituração em lote, SPED e apuração assistida

## Incremento implementado

Base: develop 0.9.0-dev.63. As alterações de recepção das PRs 86–88 e a automação de 24 horas foram preservadas. Não há migração de banco ou alteração do cofre/criptografia.

- Selecionar XMLs da caixa DF-e/NFS-e, conservar a seleção entre páginas ou preparar todos os resultados filtrados, com limite explícito de 1.000 XMLs e limites de bytes do importador existente.
- Escolher a data de escrituração do lote dentro da competência ativa. Emissão e competência declarada permanecem distintas. A seleção filtrada considera a competência do XML, quando informada, e pode encontrar consultas arquivadas em outros exercícios.
- Criar um único pacote de importação determinístico, com originais íntegros; abrir o fluxo existente de revisão de datas/CFOPs, seleção e confirmação transacional. Preparar não escritura. Não há consulta fiscal, manifestação ou emissão durante essa etapa.
- Ler NFS-e Nacional `NFSe/infNFSe/DPS/infDPS`, identificar o CNPJ completo como prestador/tomador, conservar chave, datas, total e tributos declarados. Intermediário isolado, partes ambíguas, namespace errado ou campos únicos duplicados não viram lançamentos.
- Perfil de serviços por empresa: valor contábil e seleção independente de base ISS, ISS declarado e ISS retido. Fonte, responsável e versão ficam registrados. XML sem um valor selecionado bloqueia a nota; não se usa total como base nem se presume zero.
- Copiar o perfil e os valores escolhidos para a escrituração. Mudar o cadastro não modifica notas já escrituradas. O relatório CSV consulta essas cópias históricas.
- Visualizar DANFE, DANFC-e e DACTE pelos renderizadores existentes, abrir representação de conferência NFS-e e espelhos de resumos/eventos. O DANFSe gerado localmente é identificado como representação do XML, sem alegação de documento oficial baixado, assinatura validada ou situação fiscal atual.
- Revalidar empresa, origem, ambiente, hashes, permissões, competência aberta, perfil e elegibilidade na confirmação. Resumos/eventos não viram notas completas. Versões divergentes exigem seleção explícita. Evento relacionado à NFS-e bloqueia a escrituração até o tratamento de sua situação; não há aplicação automática do evento ou declaração fictícia de cancelamento.
- Renomear o menu para **SPED**, com guias fiscais ICMS/IPI e PIS/Cofins e guias contábeis ECD/ECF. Conservar as rotas antigas para compatibilidade.
- Acrescentar a sugestão das bases ISS/PIS/Cofins explicitamente declaradas nos serviços à preparação assistida existente. Natureza, regra, fundamento e direito a crédito continuam sendo decisões conferidas.

O perfil fica em `operations/service-bookkeeping-profile-v1`, por empresa. O importador recebe revisão 5 para não reutilizar uma prévia antiga bloqueada pelo leitor anterior. Lotes/recibos anteriores continuam armazenados e legíveis. Reimportar não altera documentos já existentes por decisão silenciosa.

## Operação

1. No Fiscal, abrir DF-e ou NFS-e Nacional e filtrar os documentos.
2. Para NFS-e, cadastrar o perfil de serviços nessa tela. Editar exige `fiscal.parameters/edit`.
3. Marcar documentos ou escolher todos os resultados filtrados. Definir a data e preparar o lote.
4. Na conferência de Importações fiscais, revisar os documentos, resolver os impedimentos, selecionar os aptos e confirmar a escrituração em lote.
5. Consultar as notas em Escrituração e documentos, visualizar seus XMLs/PDFs e conferir o relatório de serviços por competência.

São exigidas as permissões nativas de leitura, importação/exportação de originais e escrituração. A confirmação conserva as permissões adicionais do domínio. O relatório de serviços usa a permissão fiscal de exportação de relatórios. Usuários/grupos continuam administrados pelo mecanismo existente.

O fluxo preserva fechamentos e apurações finalizadas. Uma nova tentativa depois de interrupção reaproveita a prévia determinística e a confirmação idempotente; não cria lançamentos paralelos. Um lote com documentos bloqueados permite selecionar expressamente os demais aptos pelo fluxo existente.

## Situação real dos geradores

| Obrigação | Disponível neste incremento | Ainda necessário |
| --- | --- | --- |
| EFD ICMS/IPI | Exportação integral da EFD 020 original importada; recorte parcial existente de NFC-e escrituradas | Arquivo integral a partir de NF-e/NFC-e/CT-e da escrituração, demais registros e apuração |
| EFD-Contribuições | Guia própria e exportação dos dados preparatórios existentes | Serializador integral, regimes, CST/naturezas, retenções, créditos, apuração e encerramentos |
| ECD | Guia contábil e exportação preparatória existente | Livro, responsáveis, mapeamentos, saldos/demonstrações, registros e validação do arquivo integral |
| ECF | Guia própria com requisitos e referência de leiaute | Recuperações, plano referencial, IRPJ/CSLL, e-Lalur/e-Lacs, regimes, serialização e validação |

**Este incremento não entrega geradores integrais de ECD, ECF ou EFD-Contribuições, nem uma EFD integral a partir de todos os XMLs.** As telas informam essa condição. Arquivo preparatório não recebe extensão ou rótulo de obrigação pronta para entrega.

NFS-e municipal não é convertida em NF-e/C100 ou CT-e/D100 na EFD ICMS/IPI. A EFD-Contribuições tem registros próprios para serviços, como A100/A170, conforme a operação e o regime. Portanto a regra de exclusão não pode ser aplicada indistintamente a todos os SPEDs.

## Implementação da geração integral — sequência necessária

1. **Contrato por empresa/obrigação/período:** responsáveis, regime, vigências, decisões e leiaute versionado. Preservar as declarações preparatórias já existentes; não inferir natureza ECD, plano referencial ou regime de contribuição de classificadores/nomes.
2. **EFD ICMS/IPI:** serializar blocos cadastrais e movimentos C/D dos modelos cobertos, a partir dos valores de escrituração; implementar apuração/ajustes, inventário e encerramentos conforme a cobertura declarada. Reconciliar totais, participantes, itens, unidades, versões e registros filhos; manter o modelo de consolidação opcional existente.
3. **PIS/Cofins:** decisão de regime e critério de receita; CST/natureza por operação; blocos A/C/D/F conforme aplicabilidade; apuração/retidos/créditos e seus históricos; geração e contadores por leiaute e vigência. Não aplicar ISS como PIS/Cofins ou converter automaticamente a alíquota cheia do Simples em tributos separados.
4. **ECD:** contrato anual/especial, I050/I051 e centros/históricos, I150/I155, I200/I250, demonstrações J, responsáveis/signatários e encerramentos. Abertura/encerramento e recuperação precisam ser fatos explícitos e reconciliados, inclusive em livros anteriores.
5. **ECF:** seleção de leiaute para ano/situação, recuperação, plano referencial, saldos e apurações por regime, controles fiscais e encerramentos. Não tratar a ECF como simples exportação das partidas da ECD.
6. **Execução e evidência:** intenção idempotente por empresa/obrigação/período; congelar versões de documentos e parâmetros, calcular contadores e totais, emitir relatório de cobertura/pendências e hash do arquivo. Alteração de origem invalida a prévia; geração não altera o livro e não transmite.
7. **Aceite:** fixtures de cenários reais anonimizados, regressões de arredondamento, créditos e fechamentos, execução no programa oficial e conferência contábil/fiscal. Registrar a versão do programa e resultado; testes de estrutura isolados não equivalem à homologação do arquivo completo.

## Preparação da apuração assistida

A memória local existente continua responsável por regras revisadas, bases, ajustes, saldos, fingerprints, finalização e transporte. O perfil de serviços e suas bases declaradas passam a alimentá-la sem perder a origem. A ampliação completa deve separar a apuração local dos dados obtidos do Fisco.

O estudo de referências recuperadas já está em `docs/RELATORIOS_PROSOFT_REFERENCIAS.md`, especialmente seções 3.5 e 9: quadros P9, controles de LRA e modelos de livros ISS. Essas referências de campos/apresentação não comprovam algoritmos tributários. Não foi executado nem novamente decompilado o pacote de binários nesta entrega.

Para CBS, foi conferida em 18/11/2026 a documentação oficial atual: credenciais/token próprios, solicitações assíncronas, tíquete/situação e arquivo final JSON. A consulta por CNPJ base usa janela incremental limitada; não é uma API de histórico arbitrário nem deve reaproveitar a autenticação A1 do ADN por suposição.

Próximos componentes concretos:

- Cofre e autorização próprios para o consumidor CBS, distinguindo matriz, filiais autorizadas e procurador. Não liberar uma base de oito dígitos a um usuário autorizado somente em uma filial por inferência.
- Jobs persistentes para solicitar, acompanhar, obter e arquivar retornos; confirmar situação antes de interpretar webhook. Proteger tokens e URLs temporárias de download; não disponibilizá-los em logs ou links operacionais.
- Leitores versionados dos JSONs oficiais de débitos, créditos, pagamentos e recolhimentos; conservar atualizações e origem de cada posição, sem somar versões como novos fatos.
- Conciliação por documento/origem/período entre escrituração e Fisco, distinguindo valor apurado, saldo, suspensão e extinção. Não tratar imposto declarado no XML ou pagamento financeiro como crédito automaticamente apropriável.
- Guias de pendências, documentos sem correspondência, ajustes justificados, aprovação e relatório comparativo; integração com os bloqueios de competência e memórias atuais.

Não há conexão CBS, envio de ajustes, confirmação oficial, geração de DARF, débito automático ou operação equivalente implementados nesta PR. A documentação desses serviços está em evolução e precisa ser fixada por versão antes do adaptador operacional.

## Referências oficiais

- EFD ICMS/IPI: [Guia Prático 3.2.4](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@download/file).
- EFD-Contribuições: [documentação atual](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes) e referências fixadas em `app/sped_generator/contributions_snapshot.py`.
- ECD: [manual leiaute 9](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecd/manuais-e-documentos-tecnicos/manual_de_orientacao_da_ecd_leiaute_9_janeiro_2026.pdf).
- ECF: [manuais e documentos técnicos](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecf/manuais-e-documentos-tecnicos).
- CBS: [índice](https://docs.receitafederal.gov.br/apuracao-cbs/), [fluxo assíncrono](https://docs.receitafederal.gov.br/apuracao-cbs/guiaapiassincrona.html), [débitos](https://docs.receitafederal.gov.br/apuracao-cbs/debito.html), [créditos](https://docs.receitafederal.gov.br/apuracao-cbs/credito.html).

## Validação e limites desta entrega

Os testes novos cobrem leitura e visualização de NFS-e, direção/identidade/datas, escrituração em lote, perfil e relatório históricos, falta de base, atualização de perfil, evento posterior à prévia, permissões revogadas, isolamento e respostas tardias na interface. As suítes anteriores permanecem ativas.

Validação local em 18/11/2026:

- Rodada principal das áreas alteradas: 226 testes backend aprovados. Após a otimização de consulta de eventos e o ajuste do repasse pela camada de negócios: 90 testes de recepção/importação/lotes e 39 de negócios/integração aprovados. A verificação final do tratamento de cancelamentos passou em 32 testes de serviços/analíticos. São rodadas com sobreposição, não uma contagem de testes distintos.
- Frontend: 248 testes aprovados e build de produção concluído. Permanece o aviso já existente de tamanho de chunks. A exportação descarta resposta recebida depois de troca de empresa ou revogação de permissão.
- Suíte backend integral executada: 1.659 testes, 45 ignorados, quatro erros nos testes de sockets Unix do atualizador Docker por `PermissionError: Operation not permitted` neste executor. Essa rodada antecedeu os ajustes finais de otimização/cancelamento, cobertos pelas rodadas específicas acima. Não foi declarada aprovação integral.

A tentativa de aceite no Chromium local foi interrompida antes de abrir o navegador: `socket() failed: Operation not permitted`, pela mesma restrição de sockets deste executor. O roteiro de relatórios foi atualizado para o menu SPED e a troca de guias; não se declarou aceite visual local.

Não foram executados deploy, consulta real do novo fluxo em produção, validação PVA/PGE, ensaio dos programas ECD/ECF ou conexão CBS. O estado e os resultados de CI ficam na descrição da PR, separados dos testes locais.
