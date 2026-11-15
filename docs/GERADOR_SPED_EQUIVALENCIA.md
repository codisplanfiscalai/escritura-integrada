# Gerador SPED: confronto da referência e incremento 1

## Proveniência e escopo

Comparação de código feita em 15/11/2026, antes da implementação, entre a develop
`050664cf5bc90a284b2ec379926fdcb0bac9f440` do Escritura Integrada e o ZIP
`geradorsped-main.zip` fornecido como referência,
911.014 bytes, SHA-256
`2c6f5044b83016a380a8b4d29e963c6769998b3bf8ce879be7100939210ad101`.
O ZIP foi materializado no executor e passou na verificação de integridade.
O arquivo privado e seu conteúdo integral não fazem parte desta PR.

PRs 25, 28, 29 e 30 já integradas; PRs abertas 33 (staging PostgreSQL) e 34
(cartões por competência) conferidas antes da edição. Nenhuma dessas frentes,
Docker, volumes, Atlas, release ou implantação integra este incremento.
Não havia AGENTS.md ou .agents/skills na árvore desta develop.

## Matriz de recursos

Caminhos da origem referem-se ao ZIP; módulos Python sem prefixo abreviam
src/gerador_sped/. “Parcial” indica recurso relacionado, sem afirmar equivalência
funcional ou de leiaute. Todos os recursos, opções e fluxos da referência
permanecem no objetivo de integração interna, por incrementos; lacuna não
significa descarte ou substituição unilateral.

| Recurso | Origem: arquivo / função | Destino existente antes desta PR | Situação / lacuna |
| --- | --- | --- | --- |
| XML NF-e/NFC-e e CT-e, ZIP e originais | src/gerador_sped/document/parsers.py; application/document_ingestion.py | app/importers.py: _xml_document, parse_file; app/core.py: preview_import, confirm_import; document_sources/imports | Parcial: leitores próprios, preview/confirmação e originais; não é o mesmo motor |
| XML para EFD ICMS/IPI | application/xml_to_sped.py: XmlToSpedConverter.convert; application/efd_icms_ipi.py: EfdIcmsIpiBuilder.build | app/importers.py: _sped somente lê; app/movement_exports.py exporta XLSX | Ausente: geração EFD a partir do Escritura |
| Parse/edição e contadores EFD | sped/engine.py: SpedFile.parse, rebuild_0990, rebuild_c990, rebuild_block9 | app/importers.py: _sped e SPED_FIELDS | Parcial: leitor 020, sem editor/serializador ou preservação de todos os blocos numa geração |
| Faturas/parcelas declaradas e geradas | billing/engine.py; application/billing_workflow.py: create_simulation, approve, materialize | app/importers.py; app/import_payables.py: _generated_payables_plan, _create_generated_payables | Parcial: FAT/DUP e geração explícita, com testes próprios; sem equivalência do workflow |
| C140/C141, inclusive modelo 55 para intercâmbio | sped/engine.py: C140C141Adapter.build; application/sped_invoice_model_policy.py: install_sped_invoice_model_policy; apps/web/src/features/invoice-export/engine.ts: exportSpedWithC140C141 | app/importers.py: _sped lê C140/C141; app/import_payables.py preserva origem | Geração ausente. Preservar requisito modelo 55/Prosoft e aviso informativo da PR25; não substituir por bloqueio geral |
| TXT de faturas Prosoft e CSV | apps/web/src/features/invoice-export/engine.ts: buildProsoftLine, exportProsoft, exportCsv | app/prosoft.py: encode_journals é CTBLCTOS LC1/LC2 contábil | Ausente para faturas: exportador contábil atual tem outro contrato |
| NFC-e diária com segmentos e CFOP/tributos | fiscal_consolidation/engine.py: FiscalConsolidationEngine.consolidate_documents; fiscal_consolidation/sped_adapter.py: SpedNfceAdapter.extract; apps/web/src/features/local-processing/consolidation.ts: consolidateSped | app/fiscal_analytics.py: fiscal_posting_lines e validate_posting_group_review agrupam itens dentro de um documento | Antes ausente entre documentos. Incremento 1: prévia documental e exportação nativa opcional C100/C190/C191/C195 sobre EFD importado; persistência e demais perfis continuam pendentes |
| Cancelamentos, lacunas, denegação/inutilização | fiscal_consolidation/engine.py: _build_occurrences, _build_segments | app/importers.py: eventos e SPED_NON_MOVEMENT; app/core.py: book_cancellation | Parcial: originais preservados; sem livro completo de sequências/eventos |
| Excel consolidado e livro/apuração | fiscal_consolidation/xlsx.py; apps/web/src/features/local-processing/xlsx-consolidated-book.ts | app/fiscal_reports.py; app/report_exports.py; app/tax_ledger.py | Relatórios existentes com contratos distintos; não há as 12 abas e livro da referência |
| Validação EFD independente/pós-geração | sped_validation/parser.py: parse_payload; validator.py: SpedIcmsIpiValidator; runner.py: OptionalSpedValidationHook | app/importers.py: _sped; app/fiscal_analytics.py; app/auditor.py | Parcial: importação e auditoria existentes; não há validador/gancho completo de geração EFD |
| Ajustes C195, DIFAL, créditos e Simples | apps/web/src/features/sped-tools/adjustments.ts: applyC195Adjustments, applyDifalAdjustments, applyCreditPdfAdjustment, applySimplesPdfAdjustment | app/tax_assessment.py e tax_ledger.py apuram valores internos | Editor EFD ausente; não há equivalência de ajustes |
| Auditoria de cruzamento e exemplos | apps/web/src/features/sped-tools/audit-engine.ts; src/gerador_sped/sped_tools | app/auditor.py e auditor_engine; tests/fixtures | Motor diferente; ferramentas/exemplos específicos da referência ausentes |
| Regras fiscais e custo de IPI | src/tax_fiscal_engine; application/efd_purchase_cost.py | app/fiscal_analytics.py; app/operational_settings.py; app/tax_assessment.py | Parcial; nenhuma regra transportada ou enquadramento presumido |
| Gerações, artefatos imutáveis e trilha | application/sped_generation.py: generate, generate_complete, read_verified_artifact | imports, document_sources, audit, export_batches e app/import_reprocessing.py | Originais/trilha existentes; histórico de gerações EFD ausente |
| Empresa, competência, contador, permissões | application/competence_workflow.py; tenant_accountants/service.py; application/access.py | app/api.py; app/db.py; app/permissions.py; app/periods.py | Serviços do Escritura devem continuar sendo a autoridade; não copiar autenticação ou banco da referência |
| Workspace interno e processamento local | apps/web/src/features/fiscal-consolidation/FiscalConsolidationPage.vue; local-processing/worker.ts | frontend/src/views/ImportView.vue, DocumentsView.vue, ProsoftView.vue | Workspace Gerador SPED e worker ainda ausentes |

## Divergência constatada no código da referência

`docs/consolidacao-fiscal-saidas.md` afirma que não cria C100 sintético.
Porém `apps/web/src/features/local-processing/consolidation-export.ts`,
`buildCompleteNfceSped` e `buildConsolidatedC100`, removem C100 regulares,
somam os campos monetários e reutilizam número/chave da primeira NFC-e do
segmento. `local-processing/worker.ts` encaminha a tarefa `sped-complete`
para essa função. O backend `EfdIcmsIpiBuilder.build` segue caminho diferente:
itera os documentos e chama `_c100` para cada um. Portanto não há uma única
equivalência implícita entre “consolidar” e “gerar SPED” na origem.

A consolidação nativa é intencional e foi preservada neste incremento em
app/sped_generator/native_export.py: consolidate_native_sped. A opção desligada
devolve os bytes originais; ligada, reproduz a primeira chave/número e as somas
C100, C190/C191, 0460/C195 e contadores. As demais chaves e linhas compõem a
trilha individual retornada. Avisos identificam a representação operacional e
não declaram conformidade legal ou aptidão de entrega de EFD. A divergência da
documentação é evidência a resolver, sem remoção da função.

## Incremento escolhido

Módulo `app/sped_generator`, com motor puro e rota de consulta autenticada
`GET /api/companies/{cid}/sped-generator/nfce-consolidation?period=AAAA-MM`.
Lê todos os documentos da competência de escrituração em snapshot, sem limite
de paginação da grade. Agrupa somente NFC-e de saída, emissão própria comprovada
pela origem XML ou IND_EMIT=0 do C100, em dia de emissão/série e segmentos
numéricos contíguos. Preserva referências individuais e valores em centavos.

Consulta opcional, sem alteração de documentos, originais, títulos ou lançamentos.
A prévia não gera SPED, não confirma importação nem grava consolidação. Datas de emissão
e escrituração permanecem distintas. Pendências de conferência continuam visíveis.
Não soma tributos nem infere CFOP, crédito ou situação eletrônica. Documentos fora
do escopo e origens insuficientes recebem motivo explícito de exclusão da prévia.

### Exportação nativa opcional integrada

POST /api/companies/{cid}/sped-generator/consolidation-export recebe import_id,
period e consolidate_nfce (booleano, padrão false); segment_on_gap (padrão true)
permite o agrupamento compacto quando false. Usa o original EFD 020 já importado,
sem novo upload e sem aplicação/banco paralelo. Exige sessão/CSRF, empresa ativa,
módulo Fiscal, exercício, consulta/exportação de documentos e exportação de
originais fiscais. Revalida permissões no snapshot e respeita limpeza autorizada.
Retorna conteúdo em base64, hashes de origem/resultado, avisos e trace por membro.
Não grava o derivado nem altera o original, movimentos, auditoria ou financeiro.

O escopo foi restringido como solicitado: modelo 65, saída e IND_EMIT=0.
Entradas, terceiros, outros modelos e situações especiais ficam preservados no
EFD. C140/C141 de modelo 55 continuam byte a byte; o aviso informativo de totais
não se torna bloqueio. Se filhos de NFC-e ainda não puderem ser agregados sem perda, o módulo retorna
o original com aviso; a exportação permanece disponível. A função
nativa não é uma representação de uma única nota real: o uso da primeira chave
é opcional e acompanha a lista completa de membros e o hash do original.

Limite comprovado: o exportador original estende C100 para 29 campos de dados;
o leitor 020 atual espera 28 (29 contando o código do registro). A saída nativa
foi preservada, com aviso explícito; sua reimportação pelo leitor atual fica
pendente de adaptação. O teste registra o mesmo SPED_FIELD_COUNT, sem alterar
importação, cobrança ou mensagens existentes. O módulo também aceita CNPJ
alfanumérico já suportado pelo Escritura; o parser frontend original só aceitou
CNPJ numérico na comparação diferencial. Nenhuma destas verificações é PVA.

## Etapas restantes

1. Interface do módulo e seleção explícita da opção na importação XML, usando o
mesmo contrato e preservando documentos individuais e trilha na confirmação.
2. Consolidação operacional persistida com versão/justificativa e invalidação
após revisão/reprocessamento; agregação tributária na escrituração e perfis
completos de eventos/ocorrências. A soma C190/C191 já existe na exportação nativa.
3. Portar a geração XML/dados do Escritura para EFD, mantendo ambas as opções
nativas: individual e consolidada. Disponibilizar consolidação na importação
para escrituração sem geração e, independentemente, depois na geração EFD.
Preservar geração C140/C141 modelo 55 para intercâmbio Prosoft; adaptar o leitor
para a saída nativa com regressão e sem perda dos campos originais.
4. Portar os demais recursos da matriz em incrementos próprios, com regressão
diferencial sintética e homologação dos formatos de intercâmbio.

Não foram usados dados reais, backups ou ambiente de produção.

## Requisitos operacionais recebidos e cobertura deste incremento

| Requisito | Cobertura e próximo incremento |
| --- | --- |
| Uso interno, todos os recursos/opções/fluxos do Gerador preservados por etapas | Módulo Python integrado ao app existente; matriz acima acompanha as lacunas. Sem aplicação paralela |
| Escolha por empresa entre EFD próprio/do cliente e geração oficial | Caminho do EFD fornecido exercitado; configuração persistida da escolha e geração XML/dados ainda pendentes. Desligar consolidação retorna o EFD fornecido byte a byte |
| Consolidação opcional na importação XML para escrituração, sem gerar SPED | Importação individual pendente/escriturada e prévia posterior testadas; consolidação persistida no ato da importação ainda pendente |
| Consolidação opcional posteriormente na geração/exportação | Exportação nativa sobre EFD importado portada, com e sem consolidação; integração ao futuro gerador XML/EFD pendente |
| Críticas fiscais/de negócio informativas, sem bloquear exportação SPED | Avisos de representação e quantidade de campos não bloqueiam. Transformação sem agregação segura retorna original com aviso; permissões, empresa e contexto continuam protegidos |
| Operações livres em competência aberta; competência fechada exige reabertura para alterar/excluir | Este incremento não altera movimentos. Exportações de leitura testadas aberta/fechada/reaberta sem mudar o estado. Revisão das demais travas legadas fica pendente, sem alteração ampla nesta PR |
| Excluir lote nunca apaga lançamentos | Não muda exclusão/limpeza; regressões existentes de limpeza de originais e segurança executadas |
| Reduzir lançamentos, melhorar desempenho e armazenamento com 90 mil NFC-e/mês | Medição sintética abaixo; reduz registros no derivado, sem redução de documentos no banco ou economia de armazenamento neste incremento |
| Preservar originais, rastreabilidade e capacidade de EFD individual | Originais e identidades individuais intactos, opção desativada devolve original. Não substitui o gerador individual da referência nem representa sua integração completa |
| Sem transmissão fiscal | Nenhuma integração de envio, cancelamento, manifestação, encerramento ou obrigação foi acrescentada |

## Validação e limites

- Validação final: **258 testes passaram em 87,249 s**, sendo 29 novos e
229 regressões existentes, após atualizar a branch sobre a develop f1aac99. Comando: PYTHONDONTWRITEBYTECODE=1, diretório de
dados temporário e PYTHONPATH contendo tests, raiz e dependências temporárias;
python3 -m unittest test_sped_generator test_sped_native_export test_core
test_evolution test_importers test_fiscal_import test_import_payables
test_generated_payables test_import_reprocessing test_reprocessing_linked_effects
test_movement_exports test_export_performance test_fiscal_series
test_fiscal_analytics test_import_package_cleanup test_bulk_security
test_migration_checkpoint -q.
- Sintaxe AST de nove arquivos Python e git diff --check passaram. A PR36 foi
atualizada sobre f1aac99 (PR33 e versão 0.9.0-dev.8), sem conflitos textuais.
Os nove arquivos Python desta frente permanecem byte a byte iguais aos do
commit 4141850 validado anteriormente; a atualização preserva a implementação
de migração incorporada pela develop, sem alterações nessa frente.
- Execução real de buildCompleteNfceSped do ZIP: três amostras sintéticas
(consecutiva, lacuna, múltiplos segmentos) × dois perfis. Os seis resultados
foram idênticos byte a byte à versão portada. Seus hashes estão no teste
test_reference_golden_bytes_for_six_synthetic_cases; não dependem do ZIP em CI.
Isso prova somente esses cenários, sem afirmar equivalência de todos os recursos.
- Preservação integral do banco sintético comparada por hash de iterdump antes e
depois de consultas/exportações repetidas, incluindo BLOB original, documentos,
títulos, journals e audit. FAT/DUP modelo 55 e totais informativos preservados.
- Primeira regressão ampliada: 181 testes, duas falhas por ausência de
BrazilFiscalReport/rarfile/py7zr no executor. Dependências fixadas no projeto
foram instaladas em pasta temporária e o conjunto repetido passou integralmente.
Sem alteração de dependências do projeto.
- Não executados: suíte integral, PVA, instalação Prosoft, navegador, Windows,
macOS, builds/instaladores, PostgreSQL operacional, produção ou dados reais.
Sem homologação jurídica de entrega. O CI anterior 43679768820 passou no commit
4141850; a atualização de base dispara nova execução, a conferir na PR.
- Opções avançadas de segmentação por cancelamento/denegação e os demais recursos
não portados permanecem na matriz; não são descartados nem apresentados como
implementados. Não há seletor visual ou configuração persistida por empresa.

### Medição de 90 mil NFC-e sintéticas

Reprodução em processos separados no executor Linux/Python 3.12:

```bash
PYTHONPATH=. python3 scripts/benchmark_sped_consolidation.py --documents 90000 --mode preview
PYTHONPATH=. python3 scripts/benchmark_sped_consolidation.py --documents 90000 --mode native
```

Amostra: 30 dias, três séries, 1.000 notas por grupo, cada documento com um C190,
sem dados reais. Uma execução por modo; não é mediana, SLA ou comparação com
produção. Inclui criação de referências no modo preview e serialização JSON da
trilha no tempo do modo native. Construção inicial do texto é medida à parte.

| Medida | Resultado observado |
| --- | --- |
| Prévia | 90.000 membros, 90 grupos, 1,044 s, RSS máximo do processo 134.500 KiB |
| Exportação nativa | 90.000 C100 → 90 C100, 3,961 s, RSS máximo 334.508 KiB |
| Construção do texto sintético | 0,340 s, fora do tempo da transformação |
| Original EFD | 15.356.798 bytes |
| EFD derivado | 29.846 bytes |
| Trilha JSON individual | 16.208.878 bytes |
| Original + derivado + trilha, sem compressão | 31.595.522 bytes |

O artefato derivado reduz os C100 em 99,9% nessa amostra e é menor que o original.
Mas manter também original e trilha custa mais bytes: **não houve economia no
banco nem redução de seus 90.000 documentos**. A medição não inclui HTTP/base64,
XML, banco, disco, UI, concorrência ou geração oficial completa. Não prova que
a aplicação ficou mais rápida; mede os motores desse incremento.

A próxima etapa precisa medir lançamentos operacionais efetivamente persistidos,
retenção/compressão reversível de originais e índices/trilha necessários para
regenerar EFD individual e consolidado. Nenhum ganho autoriza apagar XMLs,
documentos individuais, evidências ou backups. Nada foi excluído nesta medição.

## Incremento encadeado: EFD a partir da escrituração

O próximo incremento começa pelo Bloco C parcial de NFC-e próprias escrituradas,
com campos oficiais conferidos e exportação informativa, sem gerar apuração ou
blocos por presunção. Contrato, fontes oficiais, cobertura e lacunas em
[GERADOR_SPED_BLOCO_C_ESCRITURACAO.md](GERADOR_SPED_BLOCO_C_ESCRITURACAO.md).
O objetivo segue sendo a EFD integral para conferência no PVA e posterior
transmissão pelo responsável; esta etapa não caracteriza sua conclusão.
