# EFD-Contribuições: diagnóstico local somente leitura

Etapa anterior preservada: develop dev.18 `1e77a33da56a35d35ecc4b19e4fc96bc0e4cc69b`, com PR46/47 integradas. Branch exclusivamente local `feat/contributions-readonly-diagnostic-local`. Não depende das PRs43/48 e preserva suas branches e conteúdos publicados. Antes deste incremento, não havia rota de snapshot EFD-Contribuições na base; os importadores existentes tratam XML NF-e/NFC-e/CT-e e SPED EFD ICMS/IPI, sem equivalência automática com importação de Contribuições.

Continuação em 16/11/2026 sobre develop dev.20, com contratos temporais/declarativos e validação integral: [EFD_CONTRIBUICOES_DECLARACOES.md](EFD_CONTRIBUICOES_DECLARACOES.md). Os resultados abaixo pertencem à primeira etapa.

## Referência e período explícitos

Recorte confrontado: **novembro/2026**, para diagnóstico das evidências disponíveis, sem afirmar cobertura legal integral. A versão do guia é diferente da versão do leiaute e da versão do programa oficial.

| Fonte pública recuperada em 15/11/2026 | Versão/trecho efetivamente conferido | Tamanho | SHA256 |
| --- | --- | --- | --- |
| [Guia Prático oficial](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/manuais/guia_pratico_efd_contribuicoes_versao_1_35-18_06_2021.pdf/@@display-file/file) | 1.35, revisão interna 18/06/2021; páginas 1, 57, 66–67, 71–72, 105–106, 117–118, 122–123 | 4.105.830 bytes | `60eace459169238808e3e745e952fcbbbd2af6b7f933b043e8c9692b68f4d08b` |
| [NT12/2026 oficial](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/documentos-tecnicos/nota-tecnica-12-2026-reducao-linear-de-incentivos-e-beneficios-lc-224/@@display-file/file) | Página 1: orientações sobre benefícios e ajustes; não implementadas | 224.526 bytes | `9ff91fc533ae9a7c5865dde4939dbcda717287fec2f7bf5b24af0a931b35b91b` |
| [NT13/2026 oficial](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/documentos-tecnicos/nota-tecnica-013_2026-alteracoes-efd-contribuicoes-para-rtc-2027.pdf/@@display-file/file) | Página 1: controle histórico de créditos em 2026 e finalidades específicas após 2026; não implementados | 346.724 bytes | `5b588eb7a49581a4073eaaad1e1ad2c73f18781fa90fb5e46439eaaab6c1c5b1` |

Os PDFs foram lidos localmente, com visualização da tabela C170 (página 118) e da página 1 da NT13. Binários/textos extraídos/imagens ficam fora do Git. A [página oficial do guia](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/manuais/guia_pratico_efd_contribuicoes_versao_1_35-18_06_2021.pdf) permanece listando 1.35; sua data de publicação no portal em 2026 não altera a revisão interna de 2021. A tabela da página 57 registra código 006 / versão 3.2.0, início janeiro/2020. Esses dados são referências do guia (`layout_code_in_guide`), não seleção automática de leiaute completo para qualquer competência.

O [comunicado oficial da NT13](https://www.gov.br/sped/pt-br/assuntos/comunicados/efd-contribuicoes/efd-contribuicoes-publicacao-da-nota-tecnica-13-2026), publicado em 05/11/2026, distingue alterações previstas e versões futuras do PGE. Não se presumiu disponibilidade dessas versões ou encerramento geral da obrigação em janeiro/2027. Tabelas vigentes e demais notas não foram confrontadas integralmente; `complete_current_layout_review` e `official_program_validated` permanecem false. Outros meses exportam dados armazenados com aviso de recorte não confrontado; meses a partir de janeiro/2027 recebem também aviso de transição não implementada.

## Inventário origem/destino e lacunas

| Informação/registro de referência | Disponível no código atual | Tratamento neste incremento | Lacuna preservada |
| --- | --- | --- | --- |
| Identificação 0000, competência | `company_row`, `Core.documents`, documents.company_id/period/issue_date/posting_date | Empresa e competência explícitas, seleção por período de escrituração armazenado | Sem abertura de obrigação ou escolha automática de período fiscal oficial |
| Regime 0110 | companies.regime é rótulo cadastral genérico | Rótulo preservado como stored_regime_label | regime_0110 e revenue_recognition nulos; não inferidos do cadastro, CRT ou CST |
| Documentos C100 | `Core._document_values`, `_xml_document`, `_sped` | IDs, versão, modelo, direção, série do domínio/declarada, chave e datas; total armazenado em centavos como texto | efd_fiscal_inclusion nulo; não decide registros ou inclusão por modelo/cancelamento |
| Itens C170/C175 | items_json; produto, quantidade, valores e origens | Itens atuais copiados integralmente, sem transformação | Não gera C170/C175 nem presume aplicabilidade do registro |
| CST, bases, alíquotas e valores PIS/Cofins | XML: impostos achatados em taxes; SPED ICMS/IPI: raw_fields e taxes | Localiza grafias conhecidas, preservando valor e caminho em tax_evidence | Observação documental, sem validação semântica, conversão CST emitente/destinatário ou reconhecimento de crédito |
| 0150/0200/0500 | Cadastros de participantes/produtos/contas existem nos serviços de domínio; itens podem portar vínculos | Não consulta nem materializa esses cadastros adicionais | Correspondência completa de cadastros/contas com Contribuições não atestada |
| Serviços A/D/F/I | CT-e tem leitor; não há neste incremento diagnóstico de cobertura por bloco | Documentos armazenados do recorte são observados, sem filtro que escolha tratamento fiscal | Lacunas por modelo/atividade ainda exigem matriz própria |
| Apuração M, ajustes, retenções | Rotinas genéricas de regras/apurações e tax_ledgers existem | Não são consultadas ou reinterpretadas | taxable_bases, tax_due, adjustments e withholdings nulos |
| Cadeia 1100/1500 e recuperação de anteriores | `previous_credit` é serviço genérico e pode retornar zero quando não encontra período anterior | Não é chamado nem tratado como saldo EFD comprovado | credit_1100_1500_history nulo; sem preencher falta de histórico com zero |
| Rastreabilidade/originais | source/source_hash, document_sources, payload_hash, originais de imports | Todas as fontes vinculadas por empresa/documento retornam; hash do payload armazenado é distinto do hash da origem | Não inclui BLOBs/importações completas, não faz casamento presumido por nome de arquivo e não atesta assinatura dos originais |
| Integridade da consulta | Database.read(snapshot=True), permissões do domínio | Mesmo snapshot de leitura para empresa, documentos, configuração de série e fontes | Sem alteração/auditoria de escrita, contas, saldos ou lançamentos |

## Contrato de consulta

`GET /api/companies/{cid}/sped-generator/contributions-snapshot?period=2026-11`

Retorna JSON anexável com snapshot e SHA256 canônico, cabeçalhos `Cache-Control: no-store` e `X-Snapshot-SHA256`. Exige sessão, empresa/módulo Fiscal/exercício ativos, além de permissões **read e export** em fiscal.documents. Cabeçalhos opcionais de contexto conflitantes são rejeitados. Nenhuma permissão de importação, contabilização ou transmissão é concedida.

Consulta permitida em competência aberta, fechada ou reaberta; não chama fechamento, apuração ou escrita. Guardas de autorização, exercício e formato do período permanecem. Avisos de cobertura/lacunas são informativos (`blocking_export: false`), sem impedir a exportação do diagnóstico. Alterações/exclusões continuam sob os serviços e regras existentes, sem mudanças nesta frente.

`tax_evidence.fields` contém caminhos em arrays; a última chave pode conter barras de um caminho XML achatado. `stored_value` é copiado exatamente. Estado blank/null é distinto de chave ausente. Textos, inclusive códigos desconhecidos e vírgulas decimais de raw_fields, recebem stored_text_unvalidated: não significa valor fiscal válido. Números/bools/listas/objetos encontrados nos campos não são convertidos em decimais e recebem unsupported_value_type; dados e estruturas permanecem preservados com aviso. Não há arredondamento, soma de tributos ou preenchimento de valores desconhecidos.

A apresentação da série usa a configuração atual do domínio, como Core.documents; declared_series mantém o valor declarado preservado. Não há atestado de vigência histórica dessa configuração.

O snapshot não exclui documentos por estado nem converte cancelamento em decisão de exportação: observa o estado armazenado e mantém efd_fiscal_inclusion nulo. Isso não modifica as decisões Prosoft pendentes. A contagem recognized_field_observations conta ocorrências em locais de armazenamento, podendo repetir um mesmo valor em taxes e raw_fields; não representa total de tributos ou lançamentos. Uma lista vazia de documentos não atesta ausência de movimento ou dispensa da obrigação.

## Verificações e limites

Fixtures exclusivamente sintéticas, em bancos temporários. Testes em `tests/test_contributions_snapshot.py`: pipeline XML/SPED do cliente até o snapshot; CST do emitente preservado em entrada sem classificação automática; texto decimal de alta precisão; chave ausente/vazia/nula/tipo não suportado; competência versus emissão; outra empresa; contexto e permissões com revogação; período fechado/reaberto; origem/hash; determinismo e hash lógico integral de tabelas/BLOBs/auditoria sem mutação; registro cancelado sem escolha fiscal; período vazio e transição 2027 com avisos.

Execução específica: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:scripts:. python3 -m unittest test_contributions_snapshot -v` (dependências de teste instaladas, somente bancos temporários).

Resultado final na base dev.18: **368 testes distintos passaram em 149,379 s**, incluindo os 11 novos; a execução específica final dos 11 passou em 3,638 s. Verificação AST de quatro arquivos, diff-check e comparação SHA256 dos três PDFs públicos passaram. As execuções iniciais das fixtures foram corrigidas para respeitar controles já existentes de módulo/exercício e cancelamento sem origem eletrônica; nenhuma dessas regras foi alterada.

Comando de composição executado (o ambiente local acrescentou ao PYTHONPATH somente dependências de teste isoladas fora do Git):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:scripts:. python3 -m unittest test_contributions_snapshot test_core test_evolution test_account_plans test_global_account_plans test_global_fork_scopes test_plan_manager test_bulk_operations test_bulk_security test_operational_settings test_sped_generator test_sped_native_export test_sped_bookkeeping test_import_package_cleanup test_import_reprocessing test_reprocessing_linked_effects test_fiscal_sales_accounting test_fiscal_sales_composition test_ecd_snapshot test_ecd_daily_compatibility test_ecd_contracts test_ci_release test_infrastructure -q
```

Não executados suíte integral, navegador/build, PostgreSQL real ou programa oficial. Testes de infraestrutura usam mocks, sem execução Docker operacional. PRs43/48 e suas branches permanecem preservadas; esta frente não iniciou CI remoto.

Não constitui gerador, importador oficial, validação no programa oficial, apuração PIS/Cofins ou implementação da transição CBS. Nenhum dado real, backup, certificado ou documento privado foi consultado. Sem publicação de commits/PRs, CI remoto desta frente, merge, release, instalação, transmissão, encerramento de obrigação ou implantação. Escala de 90 mil documentos não foi medida para este snapshot; ele materializa o recorte em memória, como o serviço documental atual.

Próximo passo: confirmar tabelas/notas e contrato temporal completo, depois preparar classificação explicitamente declarada pela empresa, com origem/vigência, sem inferência do XML. Somente após isso, construir matrizes por bloco e cadeia histórica de créditos/ajustes; geração e validação oficial permanecem etapas separadas.
