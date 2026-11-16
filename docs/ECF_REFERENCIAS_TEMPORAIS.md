# ECF: contrato temporal de referências oficiais

Incremento de preparação, verificado em 15/11/2026, independente da PR43 e das PRs ECD46/47. Antes desta alteração, a develop 333653dc96a017469183b6aa4524cb39a483ea27 (dev.17) não possuía catálogo ECF com hashes de artefatos recuperados, seleção de revisão ou rota de consulta temporal. Esta alteração acrescenta esses metadados e sua consulta somente leitura; não gera ECF, apura IRPJ/CSLL, importa tabelas oficiais, recupera ECD ou valida arquivos no programa oficial.

## Fontes efetivamente confrontadas

- [Manual ECF leiaute 12, download oficial](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecf/manuais-e-documentos-tecnicos/manual_ecf_leiaute_12_20_05_2026_ac_2025_sit_esp_2026.docx/@@download/file): DOCX legível, 1.508.830 bytes, SHA256 `942877bdd3d443444f35758e531b1ab30ce965a62ad148707ef2d68061b9f657`. O cabeçalho interno informa **julho/2026**; o caminho conserva 20/05/2026. O dia da revisão interna é desconhecido (`revision_date: null`). Conferidos a introdução, 0000.SIT_ESPECIAL, seção 1.12 e seção 2.9. Não foi presumida validação integral do manual.
- [Catálogo oficial de tabelas e planos do leiaute 12](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecf/manuais-e-documentos-tecnicos/tabelas-dinamicas-e-planos-de-contas-referenciais-leiaute-12-atualizacao-28-05-2026): anuncia atualização de **24/09/2026**. O recurso vinculado se apresenta como `Tabelas_Dinamicas_ECF_Leiaute_12_24_09_2026_AC_2025_SIT_ESP_2026.xlsx`; o endereço conserva 28/05/2026. Nome visível e URL são preservados separadamente.
- [XLSX oficial recuperado](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecf/manuais-e-documentos-tecnicos/tabelas-dinamicas-e-planos-de-contas-referenciais-leiaute-12-atualizacao-28-05-2026/tabelas_dinamicas_ecf_leiaute_12_28_05_2026_ac_2025_sit_esp_2026.xlsx/@@download/file): 1.750.838 bytes, SHA256 `2a4c9688df7a86c1d9e4c179e8d0547c84b56746742ef7b6a73581fdff3b9ec7`. Contêiner ZIP íntegro; leitura de estrutura com `openpyxl(read_only=True, data_only=False, keep_links=False)`, sem salvar o arquivo nem executar fórmulas. São 79 abas, 76 com cabeçalhos DT_INI/DT_FIM; as outras são INDICE, PARTEB_PADRAO e PARTEB_PARTEA. `dimension_max_row` é dimensão declarada, **não contagem de registros válidos**.
- [Comunicado oficial de revisões do leiaute 12](https://www.gov.br/sped/pt-br/assuntos/comunicados/ecf/atualizacoes-do-arquivo-de-tabelas-dinamicas-leiaute-12): revisões anunciadas em 08, 15, 20, 23 e 25/07 e 24/09/2026. O comunicado de setembro cita planos do sistema financeiro (perfil B), N600/N610, N620/N630 e alterações de datas de vigência. Há ajustes retroativos também em julho. A data de publicação do pacote não equivale à vigência de todas as linhas.

Hashes dos HTMLs observados estão em `notice_provenance`. São evidência da resposta recuperada em 15/11/2026, não assinatura da Receita ou garantia de estabilidade do URL. Não há assinatura destacada conferida. Binários, HTMLs brutos, conteúdo de linhas e fórmulas não integram o repositório nem são carregados pela aplicação. A verificação dos bytes recuperados foi repetida com `verify_artifact_bytes`; tamanho e hash dos dois artefatos conferiram. Um confronto independente da leitura do XLSX confirmou todos os 79 descritores de abas do catálogo. A introdução do DOCX foi conferida diretamente para a regra de ano/situação.

## Mapa de versões e cobertura

| Referência | Revisão declarada | Escopo confirmado | Bytes/hash disponíveis | Seleção |
| --- | --- | --- | --- | --- |
| Manual leiaute 12 | julho/2026, sem dia atestado | AC2025 normal/eventos 7/8/9; especiais 1–6 em 2026 | Sim, DOCX acima | Proveniência do contrato |
| ecf12-tables-2026-07-08 | 08/07/2026 | Leiaute 12 | Não; somente comunicado | Aviso HISTORICAL_BYTES_NOT_VERIFIED |
| ecf12-tables-2026-07-15 | 15/07/2026 | Leiaute 12 | Não; somente comunicado | Mesmo aviso |
| ecf12-tables-2026-07-20 | 20/07/2026 | Leiaute 12 | Não; somente comunicado | Mesmo aviso |
| ecf12-tables-2026-07-23 | 23/07/2026 | Leiaute 12 | Não; somente comunicado | Mesmo aviso |
| ecf12-tables-2026-07-25 | 25/07/2026 | Leiaute 12 | Não; somente comunicado | Mesmo aviso |
| ecf12-tables-2026-09-24 | 24/09/2026 | Leiaute 12 | Sim, XLSX acima | Manifesto fixado, não linhas |
| Outros exercícios/leiautes/revisões | Desconhecidos neste catálogo | Não atestados | Ausentes | Aviso, sem escolher versão atual |

O recorte do leiaute reproduz a introdução do manual: situações normais/eventos do AC2025 (códigos 0, 7, 8 e 9); situações especiais de 2026 (códigos 1 a 6). **Ano normal 2026 e situações especiais 2025 não são cobertos aqui.** Datas antigas encontradas em linhas do XLSX não estendem o escopo do leiaute a esses exercícios. Esta matriz registra apenas revisões localizadas no comunicado consultado, sem afirmar inventário histórico completo.

## Matriz campo a campo

| Campo/contrato | Origem ou regra explícita | Implementado | Falta/limite |
| --- | --- | --- | --- |
| manual.layout e content_revision_label | DOCX, introdução e cabeçalho | Leiaute 12; julho/2026 | Dia interno não atestado: null |
| scope_rules.calendar_year/situation_codes | Introdução e 0000.SIT_ESPECIAL | 2025: 0/7/8/9; 2026: 1–6 | Outros recortes sem seleção |
| revisions.id/revision_date | Comunicado e recurso oficial | IDs imutáveis por revisão anunciada | Sem alias latest; histórico binário incompleto |
| source_page/notice_url/download_url/filename_from_resource | Links e nome do recurso observado | Valores separados, HTTPS em domínio oficial restrito | URL pode mudar, não representa arquivo imutável |
| verified_payload/bytes/sha256 | Bytes baixados e SHA256 calculado | Setembro verificado; julho false/null | Sem aceitar conteúdo posterior com hash diferente |
| sheets/name/dimension_max_row | Estrutura real do XLSX | Inventário de 79 abas | Sem linhas, importação ou prova de completude dos registros |
| sheets.has_validity_columns | Cabeçalhos DT_INI/DT_FIM | 76 true, 3 false | Presença de colunas não é avaliação de vigência |
| start/end | Consulta explícita, ISO, intervalo ordenado dentro de um ano | Fronteiras inclusivas do recorte do catálogo | Não são validação completa de 0000.DT_INI/DT_FIN |
| situation | Código explícito 0000.SIT_ESPECIAL | 0–9 confrontados com escopo | Não deriva de regime, documentos ou empresa |
| event_date | Data explícita do evento, referência a 0000.DT_SIT_ESP | Para 1–9; deve estar no recorte consultado | Não inferida do fim; esse guard é limite da consulta, não validador fiscal completo |
| revision_id | Escolha explícita | Uma única revisão; duplicata é ambígua | Ausência não escolhe mais recente |
| sheet | Nome explícito do inventário | Aba conhecida ou manifesto inteiro com aviso | INDICE não representa tabela; nenhum perfil/regime é escolhido |
| selection_sha256 | Hash canônico de consulta normalizada e manifesto selecionado | Determinístico, independe de novas revisões no catálogo | Não é assinatura ou hash de ECF |
| catalog_sha256 | Hash canônico de todo catálogo retornado | Reprodutibilidade da resposta | Pode mudar ao adicionar revisão; seleção antiga permanece fixada |
| rows_selected/row_effectivity_validated | Contrato de cobertura parcial | Sempre false | Próxima etapa: analisar linhas e vigências documentadas por revisão |
| client_plan_materialized/generates_ecf/official_program_validated | Limite funcional explícito | Sempre false | Não cria plano, classificações ou arquivo fiscal |
| warnings[].blocking_export/can_export_catalog | Avisos informativos e consulta de leitura | false/true inclusive dados inválidos/ambíguos | Segurança e autenticação continuam aplicadas |

## Consulta e integridade

`GET /api/sped/ecf-references?start=2025-01-01&end=2025-12-31&situation=0&revision_id=ecf12-tables-2026-09-24&sheet=L100B`

Retorna JSON anexável, `Cache-Control: no-store`, catálogo/hash e seleção com avisos. Para especial 2026, informar situação 1–6 e `event_date` no recorte. Revisão posterior ao ano-calendário pode ser escolhida explicitamente quando o manual dá cobertura; publicação não é data da escrituração. Consulta sem parâmetros também exporta o catálogo com aviso de seleção ausente.

Não há download de rede em runtime. `verify_artifact_bytes(content, reference)` compara bytes fornecidos, tamanho e SHA256 fixados, exigindo URL oficial HTTPS. O resultado não afirma assinatura do publicador. Uma futura obtenção do URL deve passar nessa conferência antes de usar o conteúdo; se o URL mudar, a revisão antiga deve continuar sem fallback silencioso. Metadados e hashes não substituem retenção do binário de referência para reprodutibilidade futura.

Campos desconhecidos, parâmetros repetidos, datas inválidas, escopo ausente, revisão duplicada, abas ausentes e procedência incompleta deixam `selected_reference: null` e produzem avisos exportáveis. `selected_manifest` significa apenas seleção do manifesto fixado. Mesmo nesse estado há aviso de vigência de linhas não avaliada e binário não distribuído.

A rota exige sessão autenticada. Os metadados são globais e de fonte pública, sem vínculo com cliente e sem conceder permissões de leitura/exportação da escrituração. Nenhuma configuração de empresa, plano global/próprio, conta, saldo, lançamento, permissão ou competência é modificada. A consulta funciona em competência aberta/fechada/reaberta. As regras existentes para alterações/exclusões e reabertura permanecem nos serviços de domínio. Não foi criado caminho de assinatura/transmissão ou fechamento de obrigação.

## Validação e próximos passos

`tests/test_ecf_references.py` usa descritores normativos públicos e fixtures sintéticas; bancos temporários, sem leitura de dados do operador. Cobre fronteiras de anos/datas, códigos de situação, revisão conhecida/desconhecida, histórico sem bytes, evolução sem mudar seleção fixada, ambiguidade, proveniência e corrupção de bytes, ausência de vigência de linhas, determinismo, autenticação/permissões e hash lógico integral de todas as tabelas/BLOBs/auditoria antes/depois das consultas. Confere leitura em competências abertas, fechadas e reabertas, empresas distintas e usuário sem acesso a empresas. CI descobre o novo teste automaticamente.

Execução específica: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:scripts:. python3 -m unittest test_ecf_references -v` (dependências de teste instaladas; somente bancos temporários).

Resultado local na base dev.17 (`333653d`): **355 testes distintos passaram em 149,706 s**, incluindo os 17 testes ECF. A rodada anterior na base dev.16 passou 278 testes em 126,434 s; são regressões repetidas, não um segundo conjunto a somar. A execução específica inicial passou os 17 testes em 2,125 s. AST de quatro arquivos Python, JSON do catálogo e `git diff --check` passaram.

Comando de composição executado (prefixo local adicional de PYTHONPATH apontou apenas dependências isoladas já instaladas fora do Git):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:scripts:. python3 -m unittest test_ecf_references test_core test_evolution test_account_plans test_global_account_plans test_global_fork_scopes test_plan_manager test_bulk_operations test_bulk_security test_operational_settings test_sped_generator test_sped_native_export test_sped_bookkeeping test_import_package_cleanup test_import_reprocessing test_reprocessing_linked_effects test_fiscal_sales_accounting test_fiscal_sales_composition test_ecd_snapshot test_ecd_daily_compatibility test_ci_release test_infrastructure -q
```

Não executados localmente: suíte integral, navegador/build da interface, PostgreSQL real, instaladores, avaliação de todas as linhas/formas das planilhas, apuração/geração ECF ou validação no programa oficial. Testes de infraestrutura usam mocks; nenhum comando Docker operacional, instalação, migração ou acesso a produção foi realizado. CI remoto deve ser conferido separadamente da aprovação local.

Próximo incremento: retenção/verificação dos binários por revisão e parser somente leitura das linhas com identificação de tabela, chaves, perfil e regras DT_INI/DT_FIM confrontadas com fonte oficial. Só depois disso: vinculação referencial explícita por empresa/plano e validações de cobertura. Não inferir regime, preencher classificação ou escolher plano do cliente. Recuperar binários históricos faltantes sem confundir comunicado com conteúdo verificado. Geração/apuração ECF e validação no programa oficial seguem fora deste incremento. Nenhuma implantação decorre da publicação da PR.
