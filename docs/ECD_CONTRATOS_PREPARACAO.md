# ECD: contratos explícitos de hierarquia, natureza e abertura

## Entrega e dependência

Continuação encadeada à [PR46](https://github.com/codisplanfiscalai/escritura-integrada/pull/46), head/base `73206ec21a935af7de855010e486d60a6719395a`. A PR46 estava aberta, draft, sem conflito e com [CI144 aprovado](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43706383173). Nova worktree/branch; nenhuma atualização foi feita na branch da PR46. Após sua integração, retargetar a continuação para develop e repetir checks.

A rota existente `GET /api/companies/{cid}/sped-generator/accounting-snapshot` passa a acrescentar `preparation_review`. O snapshot tem **schema_version=2**, mantendo os campos anteriores. O novo bloco tem seu próprio schema_version=1. Não há endpoint de gravação, migração de schema, mudança de classificações, serializador ECD, assinatura ou transmissão.

O módulo lê declarações ECD **explicitamente preservadas nos metadados do plano** pelos serviços existentes. Aponta faltas/inconsistências e mantém a classificação do domínio e os candidatos antigos intactos. `classification_applied=false`, `complete_ecd=false` e `warnings_block_export=false` são explícitos. Abertura atestada continua indisponível: valores desconhecidos não recebem zero.

## Fonte oficial: maio continua indisponível

Tentativas em 15/11/2026, fora do repositório:

| Alvo oficial | Resultado observado |
| --- | --- |
| [Página da revisão PDF maio/2026](https://sped.rfb.gov.br/item/show/7990) | Referência localizada na pesquisa oficial; existência/índice não equivalem a confronto do conteúdo. |
| [Download PDF 7990](https://sped.rfb.gov.br/arquivo/download/7990) | `HTTP Error 503: Service Unavailable`. |
| [PDF estático identificado na pesquisa](https://sped.rfb.gov.br/estatico/71/1BD273E4A9F51ED8EF01AC3A6BC15812A3481F/Manual_de_Orienta%C3%A7%C3%A3o_da_ECD_Leiaute_20_maio_2026.pdf) | Download no executor: HTTP503. Abertura pela ferramenta web: timeout. |
| [Word estático oficial de maio](https://sped.rfb.gov.br/estatico/27/EDB92905CCEFDC62254C0E086482C0D7326305/Manual_de_Orienta%C3%A7%C3%A3o_da_ECD_Leiaute_20_maio_2026.docx) | `HTTP Error 503: Service Unavailable`. |

**A revisão de maio não foi recuperada nem marcada como revisada.** Não se supõe equivalência com janeiro. Avanço limitado ao recorte de **AC2025, leiaute9/I010.COD_VER_LC9.00**, sustentado pelo [manual oficial janeiro/2026 efetivamente disponível](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecd/manuais-e-documentos-tecnicos/manual_de_orientacao_da_ecd_leiaute_9_janeiro_2026.pdf/@@display-file/file), SHA-256 `7ddf47755f616ecd76671b8be9c8b61e30adbb0e8408634e45af95f616119b2e`. Nesta etapa, regras I050 das páginas 119/120 também foram renderizadas e conferidas visualmente; tabela de natureza na página118, saldos observados versus campos I155 nas páginas133–135, conforme matriz anterior. PDF, imagens e texto extraído não são publicados nesta PR.

Não foram avaliados todos os registros/regras, revisões posteriores ou o programa oficial. `may_2026_recovered=false` permanece no resultado. Consultas de outros exercícios continuam disponíveis com os avisos de referência da PR46.

## Declaração opcional e origem

Namespace aditivo da conta no formato nativo já aceito pelo domínio:

```json
{
  "access_code": "00101",
  "ecd_preparation_v1": {
    "DT_ALT": "2024-01-01",
    "COD_NAT": "01",
    "NIVEL": 2,
    "COD_CTA_SUP": "00100"
  }
}
```

Exemplo inteiramente sintético e parcial: não é plano real nem conta a importar por esta rota. `DT_ALT` usa ISO no contrato interno, não a formatação final de TXT ECD. A leitura não grava essa declaração. Importação/adoção de planos continuam nos serviços e permissões existentes; nenhuma regra Prosoft foi usada ou alterada.

`declared_metadata` usa a mesma precedência de `AccountPlansMixin._plan_state`: metadados locais, quando presentes; caso contrário, metadados da entrada global efetiva. Não procura outro plano para preencher lacunas. Mantém lote, entrada/plano global, tipo de origem e hash da declaração. A definição de conta corrente continua identificada pelo snapshot da PR46, com versão/aliases próprios.

Somente os quatro campos são expostos em `declared_fields`. Outras chaves do namespace são listadas como ignoradas, sem copiar seus valores; extras alheios ao namespace não são exportados. Alegações como `opening_attested` não criam atestado. JSON inválido, não finito, Unicode não serializável ou namespace de tipo incorreto viram diagnóstico sem corrigir a origem nem bloquear o download.

## Matriz campo a campo e limites das verificações

| Campo/contrato | Origem e conferência implementada | Limite explícito |
| --- | --- | --- |
| I050.COD_CTA | Código real da conta, preservando zeros; resolução exata no plano efetivo da empresa | Não usa ID técnico ou classificador como código ECD. Código duplicado torna a resolução ambígua. |
| I050.IND_CTA | Propriedade `analytical` já armazenada; conta superior declarada deve ser sintética | Nenhuma conversão de conta/nível ou alteração do plano. |
| I050.DT_ALT | Declaração ISO explícita; tipo/data inválidos são apontados; aviso por ano posterior ao ano final | A regra de janeiro compara anos. Não se cria regra nova de proibição de data posterior ao fim de um recorte no mesmo ano. Vigência histórica não é atestada. |
| I050.COD_NAT | Somente declaração explícita, confrontada com códigos01/02/03/04/05/09 da tabela de janeiro | Nunca inferida de `nature=debit/credit`, grupo do relatório, código ou exemplo. Ausente permanece ausente. |
| I050.NIVEL | Inteiro explícito ≥1; nível do filho deve superar o do superior declarado | Não conta segmentos/pontos do classificador nem impõe silenciosamente adjacência por diferença1. |
| I050.COD_CTA_SUP | Acima do nível1, ausência é lacuna; no nível1, superior informado é inconsistente; código deve existir uma vez na própria empresa | Não procura parentes por prefixo nem em outro plano/empresa. Não cria conta ou referência. |
| Natureza do superior | Para nível declarado >2, compara naturezas explícitas; natureza superior ausente/inválida deixa a comparação pendente | Condição da página120; não amplia essa regra para nível2 por decisão própria. |
| Regra condicional de nível mínimo | Dependência I010.IND_ESC indicada como pendente | O tipo de livro não está definido no domínio; não presumir G/R/B nem afirmar avaliação completa da condição de nível4. |
| Consistência do grafo | Ciclos/self-parent identificados por percurso iterativo | Diagnóstico estrutural, sem corrigir arestas ou escolher automaticamente uma hierarquia. |
| I155.VL_SLD_INI / VL_SLD_FIN | Saldos ECD continuam null; valores `recorded_*` e suas partidas permanecem disponíveis | Total balanceado e ausência de movimentos não atestam abertura, completude ou inatividade. |
| Abertura explícita do domínio | Eventos `opening` vinculados aos lançamentos, datas, hashes, posição anterior/no intervalo e referência de estorno | Não escolhe abertura mais recente nem transforma lançamento em saldo inicial. Múltiplas datas são visíveis. |
| Abertura atestada | `attestation_status=not_available_in_current_domain`, `attested_opening_balances=null` | Não há cadastro/serviço confiável de atestação nesta entrega. Nenhum valor declarado nos extras preenche esse papel. |

Estados por conta: `missing`, `declared_needs_review`, `inconsistent` ou `consistent_for_preparation`. O último significa somente que o recorte de verificações encontrou dados explícitos coerentes; não significa conta/plano aprovado pelo PGE ou ECD completa. Campos faltantes são listados separadamente. Todos os diagnósticos têm `blocking=false`.

A referência Jan/2026, os condicionais ainda não avaliados e o bloqueio de transferência de maio ficam registrados. Não se implementam I051, demonstrações, encerramento, responsáveis ou assinatura a partir destes metadados.

## Abertura: distinção entre observação, evidência e atestado

`opening_contract.observed_balances` reutiliza os saldos anteriores observados da PR46, com conta/centro e partidas de origem. `explicit_opening_postings` referencia os lançamentos efetivos com auditoria de abertura, inclusive se posteriormente estornados. São evidências diferentes e não são somadas novamente.

O contrato de futura atestação exige definir empresa/exercício/corte, completude histórica, identificação de contas/centros, evidência de origem e responsável/revisão próprios. É uma dependência funcional pendente, não uma nova trava para exportação. O leitor atual sempre diferencia esses dados de abertura atestada e não oferece comando para atestar ou fechar obrigação.

## Integridade e segurança

A leitura dos metadados ocorre na mesma conexão `db.read(snapshot=True)` do snapshot, depois das permissões existentes. Não há escrita em lançamentos, definições, lotes, auditoria ou banco. Conta global sem uso continua virtual; plano local/global e seu vínculo são preservados. A resolução do grafo usa somente contas já lidas da empresa ativa.

Os campos anteriores permanecem intactos; `preparation_review` e a revisão de schema entram no hash canônico do snapshot. Hashes dos lançamentos não são refeitos por causa da inspeção e continuam explicando os mesmos dados de origem. Repetição com insumos iguais é determinística.

Competência fechada permite os mesmos bytes de leitura. Alterações/exclusões não são acrescentadas nem liberadas por esta etapa. Os exportadores SPED existentes e as frentes Prosoft, recepção, Docker, contabilidade diária e Atlas não têm alterações. O único ajuste no CI é incluir a base encadeada `feat/ecd-bookkeeping-snapshot`, mantendo `contents: read`.

## Validação

Verificação específica: **44 testes passaram em 15,014s**, sendo 19 novos e os25 do snapshot. Cobrem campos ausentes, códigos/naturezas explícitos, ciclos, cadeia de2500 contas sem recursão, superior ausente/analítico, regras condicionais de natureza, datas, metadados malformados, planos globais/próprios e distintos por empresa, origem/hash, desconhecidos sem zero, abertura/estorno e leitura fechada. Hash de `iterdump()` integral é comparado antes/depois das leituras, incluindo BLOBs e auditoria, somente em bases sintéticas.

**343 testes distintos passaram:** 296 em 140,940s (19 novos e277 regressões), mais47 de CI/infraestrutura em0,667s. AST dos três arquivos Python, YAML, filtro da base encadeada e `contents: read` conferidos; diff-check passou.

Comando amplo, sempre em banco temporário: `PYTHONDONTWRITEBYTECODE=1 ESCRITURA_DATA_DIR=<temporário> PYTHONPATH=<dependências isoladas>:tests:. python3 -m unittest test_ecd_contracts test_ecd_snapshot test_core test_evolution test_global_account_plans test_global_fork_scopes test_account_plans test_plan_manager test_journal_query_loading test_journal_participants test_accounting_report_models test_report_models_api test_bulk_operations test_bulk_security test_operational_settings test_sped_generator test_sped_native_export test_sped_bookkeeping test_import_package_cleanup test_import_reprocessing test_reprocessing_linked_effects -q`. CI/infra: `PYTHONPATH=<dependências isoladas>:tests:scripts:. python3 -m unittest test_ci_release test_infrastructure -q`.

Branch/PR duplicada e SHA da base foram conferidos antes da publicação; hash/CI remoto serão relatados na descrição da PR. Não executados programa oficial ECD/PGE, revisão maio completa, assinatura/transmissão, navegador, PostgreSQL operacional, escala de produção, builds ou suíte integral.

Próximo passo: recuperar a revisão maio, confrontar os condicionais pendentes e definir os contratos de vigência/atestado com evidência explícita antes de qualquer serializador. A PR46 e esta continuação são preparações parciais, sem promessa de validade oficial.
