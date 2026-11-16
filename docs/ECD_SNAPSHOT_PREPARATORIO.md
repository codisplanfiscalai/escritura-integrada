# Snapshot contábil rastreável para preparação da ECD

## Cobertura entregue e base

Incremento independente, iniciado em `develop a8ac6902aab76ebe66444d2818ea0cbd9c65e4d4` (dev.13), após conferir PRs/branches. PRs36/37 já estavam integradas. A [matriz da PR43](https://github.com/codisplanfiscalai/escritura-integrada/pull/43) orienta a preparação, mas seu código não é dependência e sua branch não foi alterada. PRs39/42,40/44,41,45 e Atlas permanecem fora deste diff.

A nova rota interna **GET `/api/companies/{cid}/sped-generator/accounting-snapshot?start=2025-01-01&end=2025-12-31`** entrega JSON UTF-8 canônico, com SHA-256. O recurso é um snapshot contábil preparatório; o nome da rota não o apresenta como gerador/importador de uma obrigação oficial. Não é TXT ECD, livro oficial, gerador completo, assinatura ou transmissão. `complete_ecd=false`, `validated_in_official_program=false`, `transmitted=false` e `candidates_are_serialized_ecd_records=false` são explícitos.

A preparação confrontada usa **ano-calendário 2025, leiaute 9, referência I010.COD_VER_LC 9.00**, manual oficial de janeiro/2026 (ADE Cofis 1/2026). O tipo de livro da empresa não é inferido: `book_kind=null`. Outros exercícios podem consultar seus dados, com aviso de recorte não conferido; nenhuma mudança automática de versão oficial é feita.

## Fonte oficial e limite da revisão

- [Portal oficial do manual de janeiro/2026](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecd/manuais-e-documentos-tecnicos/manual_de_orientacao_da_ecd_leiaute_9_janeiro_2026.pdf): informa leiaute 9 desde AC2020 e ausência de mudança para AC2025.
- [PDF oficial efetivamente baixado](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecd/manuais-e-documentos-tecnicos/manual_de_orientacao_da_ecd_leiaute_9_janeiro_2026.pdf/@@display-file/file), 2.971.696 bytes, SHA-256 `7ddf47755f616ecd76671b8be9c8b61e30adbb0e8408634e45af95f616119b2e`. Conferência em 15/11/2026. Extração com Poppler; revisão visual das tabelas nas páginas 118,133,143,148. Demais campos abaixo conferidos no texto das páginas indicadas.
- [Portal oficial da revisão maio/2026](https://sped.rfb.gov.br/item/show/7990): a revisão existe, mas o download `https://sped.rfb.gov.br/arquivo/download/7989` retornou **HTTP 503 Service Unavailable** neste executor. Confronto integral dessa revisão permanece pendente; não se declara que janeiro é o manual mais recente.

O PDF permanece fora da branch. A matriz cobre somente o recorte preparatório abaixo, não todos os registros/regras do manual. As revisões futuras e o programa oficial precisarão ser conferidos antes de qualquer serializador.

## Origem dos dados e comportamento anterior

| Fonte existente | Uso no snapshot | Preservação/limite |
| --- | --- | --- |
| `Core.journals`, `Core._journal`, tabelas `journals`/`journal_lines` | Mesmas partidas, números, datas, competências, histórico e relações de estorno | Leitura em lote sob uma única transação de snapshot, sem modificar esses serviços. Estornado e compensação continuam presentes. Não usa o filtro de um relatório resumido para criar lançamentos. |
| `effective_accounts`, `resolve_account` | Mesma visão de definições que o domínio resolve por empresa | Não chama resolução com `materialize=True`, não cria referências positivas e não copia plano global. Mantém IDs positivos/virtuais negativos, código com zeros, classificadores repetidos, versão e origem global. |
| `company_account_plan_bindings`, entradas globais e aliases | Plano realmente escolhido, modo shared/own, versão, SHA da fonte e aliases conhecidos | Não escolhe 050 por padrão, não troca plano nem usa código Prosoft como código ECD. Plano 050 e outro plano são testados com definições inteiramente sintéticas. Sem vínculo global, mantém `plan_binding=null` e contas locais. |
| `ReportsMixin.business_report` | Referência independente para reconciliar os saldos observados | Teste compara abertura/fechamento com o balancete existente. O snapshot não gera demonstrações J100/J150 nem encerra contas. |
| `BusinessCore.create_opening`, auditoria `opening` | Preserva abertura explícita como lançamento e identifica seu evento | Não converte automaticamente esse lançamento em saldo inicial ECD nem o soma duas vezes. Tratamento contábil para a futura ECD continua pendente. |
| Importação CSV contábil confirmada | Referências de lote, arquivo, hash e seleção vinculadas ao lançamento | Sem conteúdo original/base64, sem tratar CSV como ECD. Não modifica nem apaga o lote. |
| Vínculos atuais de documentos/baixas e auditoria de lançamentos | IDs/relações e eventos contábeis, com filtro por empresa | Sem XML, valores fiscais, descrições financeiras ou arquivos de outros módulos. Reconstrução histórica completa pela auditoria fiscal e integrações das PRs39/42 não fazem parte desta entrega. |

## Contrato de leitura, precisão e faltas de dados

O intervalo é inclusivo, dentro de um exercício; datas inválidas/invertidas e intervalo entre exercícios são erros de contrato. Empresa ativa, módulo Contábil e ano da sessão devem corresponder. Headers opcionais de contexto divergentes são rejeitados. O usuário precisa de `accounting.journals:read/export` e `accounting.accounts:read`, revalidados no snapshot. Metadados das contas não concedem acesso a originais ou permissões de outros módulos.

`journals` contém somente movimentos entre start/end. `opening_history.journals` conserva separadamente os lançamentos anteriores ao início, inclusive de exercícios anteriores **da mesma empresa**, necessários para explicar o saldo observado. Nenhum lançamento posterior ao final entra nos totais; uma referência de estorno posterior permanece como referência, sem antecipar sua movimentação. Não se filtra o original por estar marcado `reversed`.

`monthly_balances` divide o intervalo em meses/frações contíguas e sem sobreposição, por **conta + centro**, inclusive centro não informado. O agrupamento usa a data armazenada; divergência entre data e competência é preservada e avisada. A chave interna nunca é apenas o classificador, que pode se repetir.

Valores monetários têm `{cents: "123", decimal: "1.23"}`: ambas strings, sem float, arredondamento ou perda em clientes JavaScript. O cálculo usa inteiros de precisão arbitrária. Débito positivo e crédito negativo compõem o saldo observado; zero tem indicador D/C nulo. O limite atual por lançamento do domínio é preservado; teste agrega 91 lançamentos válidos até superar `2**53` centavos.

- `recorded_*` é a soma matemática das partidas disponíveis. Zero observado em conjunto vazio não atesta saldo legal zero, inatividade ou completude da escrituração.
- `ecd_opening_balance` e `ecd_closing_balance` permanecem **null**, pois a completude histórica e o tratamento de abertura/encerramento não foram atestados.
- IDs das partidas explicam o saldo anterior inicial e os movimentos mensais, sem repetir todo o histórico em cada mês. Fechamento observado de um mês transporta-se ao seguinte.
- Conta/centro não resolvido, total do cabeçalho divergente ou competência inconsistente produzem avisos e preservam o que foi armazenado. Não corrigem silenciosamente o banco nem bloqueiam o JSON.
- Período sem movimentos tem listas vazias, aviso e indicadores de cobertura incompleta. Fração de mês avisa; não comprova situação especial do livro.
- Datas/natureza/hierarquia ECD, plano referencial, tipo de lançamento, moeda funcional, participantes ECD, responsáveis e demonstrações faltantes não são inventados. Nome/histórico/código de acesso atuais não comprovam vigência histórica.

## Matriz campo a campo do recorte conferido

`ecd_candidates` guarda candidatos de origem com suas faltas; não contém linhas ECD nem formatação final do leiaute. Datas são ISO e dinheiro é estruturado como acima. `REG` dos registros listados não é emitido. Moeda funcional não foi declarada pela empresa; campos MF não recebem zero por padrão.

| Registro/campo oficial | Origem/candidato no JSON | Estado e validação pendente |
| --- | --- | --- |
| I010.IND_ESC | `coverage.book_kind=null` | Não inferir G/R/A/B/Z do uso do Diário interno. P.102/103. |
| I010.COD_VER_LC | `reference.I010_COD_VER_LC_reference=9.00` | Referência de pesquisa, não registro emitido. P.102/103. |
| I050.DT_ALT | `accounts[].ecd_candidates.DT_ALT=null` | Data de alteração do plano não é data de exportação/primeiro lançamento. P.117/118. |
| I050.COD_NAT | `COD_NAT=null` | Natureza ECD da conta não é D/C nem automaticamente o grupo de relatório interno. |
| I050.IND_CTA | `analytical` → A/S | Propriedade explícita da definição efetiva; preservar inativas e sintéticas para conferência. |
| I050.NIVEL | `NIVEL=null` | Hierarquia formal precisa ser mapeada; não contar pontos do classificador por suposição. |
| I050.COD_CTA | `access_code` preservado | Código de conta do domínio, com zeros; não ID técnico, classificador ou código Prosoft. |
| I050.COD_CTA_SUP | `COD_CTA_SUP=null` | Classificadores repetidos impedem presumir conta superior por prefixo. |
| I050.CTA | `name` efetivo | Definição atual com versão/origem; vigência histórica não atestada. |
| I100.DT_ALT | `cost_centers[].ecd_DT_ALT=null` | Data formal não disponível. P.130. |
| I100.COD_CCUS | Código do centro referenciado | Preservar código e ID internos; ausência continua null. |
| I100.CCUS | Nome do centro referenciado | Somente centros efetivamente referenciados nas partidas lidas. |
| I150.DT_INI | `monthly_balances[].start` | Início do recorte mensal observado; não resolve situação especial. P.131. |
| I150.DT_FIN | `monthly_balances[].end` | Final inclusive, sem duplicar mês; regras de livro oficial ainda não aplicadas. |
| I155.COD_CTA | Conta do grupo → `access_code` | Grupos por ID real/virtual da conta, sem colapsar classificadores. P.133-135. |
| I155.COD_CCUS | Centro do grupo → código/null | Centro vazio permanece distinto dos centros nomeados. |
| I155.VL_SLD_INI | `ecd_opening_balance=null` | `recorded_opening` serve para conferência, não substitui abertura ECD atestada. |
| I155.IND_DC_INI | `recorded_opening_dc` de conferência | D/C pelo sinal observado; zero não recebe indicador inventado. |
| I155.VL_DEB | `recorded_debits` | Soma das partidas a débito no recorte; conciliar com cabeçalhos e I250 futuro. |
| I155.VL_CRED | `recorded_credits` | Soma das partidas a crédito; não compensar estorno antes de contabilizar ambos. |
| I155.VL_SLD_FIN | `ecd_closing_balance=null` | `recorded_closing` é conferência do histórico disponível, sem atestado de completude. |
| I155.IND_DC_FIN | `recorded_closing_dc` de conferência | Mesmo limite do saldo inicial. |
| I155.VL_SLD_INI_MF / IND_DC_INI_MF | `coverage.functional_currency=null` | Sem moeda funcional e conversão declaradas. |
| I155.VL_DEB_MF / VL_CRED_MF | Não preparados | Nenhuma cópia automática dos valores do domínio. |
| I155.VL_SLD_FIN_MF / IND_DC_FIN_MF | Não preparados | Dependem das definições I020/moeda funcional. |
| I200.NUM_LCTO | `number` como string | Identificação real do lançamento; ID interno mantido separadamente. P.142/143. |
| I200.DT_LCTO | `date` | Data original, sem substituir por competência escolhida. |
| I200.VL_LCTO | Total armazenado no cabeçalho | Mantido mesmo se divergir; `reconciliation` expõe totais de partidas e incompatibilidade. |
| I200.IND_LCTO | `IND_LCTO=null` | Não inferir encerramento/extemporâneo/normal de texto, estorno ou documento ABERTURA. |
| I200.DT_LCTO_EXT | `DT_LCTO_EXT=null` | Não inferir data do fato de nota, importação ou estorno. |
| I200.VL_LCTO_MF | `VL_LCTO_MF=null` | Sem conversão de moeda funcional. |
| I250.COD_CTA | Conta resolvida da partida → código | Partida original e compensação preservadas. P.147-149. |
| I250.COD_CCUS | Centro da partida → código/null | IDs e dados atuais preservados separadamente. |
| I250.VL_DC | Débito ou crédito armazenado | Valor positivo da partida; contas nunca são trocadas pelo sinal. |
| I250.IND_DC | Lado efetivo da partida → D/C | Sem usar natureza padrão da conta como lado do lançamento. |
| I250.NUM_ARQ | `NUM_ARQ=null` | Referência interna de lote/arquivo não é automaticamente documento arquivado ECD. |
| I250.COD_HIST_PAD | `COD_HIST_PAD=null` | Histórico padrão ECD/I075 não mapeado. |
| I250.HIST | `journal.history`, origem explicitada | O domínio atual possui histórico no cabeçalho; não se inventa complemento específico por partida. |
| I250.COD_PART | `COD_PART=null`, `participant_id` interno preservado | ID interno não vira código 0150/0180 sem mapeamento explícito. |
| I250.VL_DC_MF / IND_DC_MF | Ambos null | Sem conversão/natureza de moeda funcional declaradas. |

Divergência observada no manual de janeiro: a introdução de I200 menciona tipo X; a tabela de valores de IND_LCTO nessa página exibe N/E. O snapshot não escolhe uma interpretação nem preenche o campo. Confrontar revisão posterior e programa oficial antes de serializar.

Fora do recorte: cabeçalhos/cadastros completos, I051/I052/I053, I075, I157, encerramentos, livro auxiliar, demonstrações J, signatários, contadores e todos os demais registros/regras. Nenhum plano referencial, saldo de abertura ou lançamento de encerramento é produzido.

## Segurança, imutabilidade e fechamento

Uma conexão `db.read(snapshot=True)` lê os insumos. Não há mutação, auditoria de exportação, materialização de conta, gravação de geração, hash com relógio atual ou assinatura. O hash `snapshot_sha256` é SHA-256 de `pack(snapshot).encode("utf-8")`, sem o envelope/hash e a quebra final do download. O hash por lançamento exclui somente seu próprio campo de hash. Ambos usam JSON canônico; repetição com insumos iguais produz bytes iguais. Mudança real de dados/definições/vínculos pode mudar o hash.

Competência fechada permite o snapshot e mantém os mesmos bytes; fechamento/reabertura não muda movimentos. O novo código não chama `ensure_open`, não concede ações e não modifica políticas de alteração/exclusão. Regressões de períodos e operações em lote verificam a proteção existente. Avisos contábeis/fiscais desta preparação são informativos, sem impedir download.

Fixtures exclusivamente sintéticas. Os testes de leitura comparam SHA-256 de `iterdump()` integral (todas as tabelas, BLOBs, auditoria e arquivos armazenados) antes/depois. Nenhum backup, documento ou plano real foi lido ou copiado para testes, GitHub, logs ou artefatos.

## Validação e próximos passos

**324 testes distintos passaram:** 277 em 128,899 s, incluindo os 25 novos do snapshot e 252 regressões de contas próprias/globais, escopos de cópia, participantes, carregamento, relatórios, operações em lote, fechamento, parametrização, SPED e retenção/reprocessamento; mais 47 CI/infra em 0,769 s. As primeiras rodadas ajustaram apenas fixtures: exercícios de 2025 ainda não cadastrados, limite válido por lançamento e rota/versão explícita de desmembramento do plano.

Comando amplo (banco temporário, fixtures sintéticas): `PYTHONDONTWRITEBYTECODE=1 ESCRITURA_DATA_DIR=<temporário> PYTHONPATH=<dependências isoladas>:tests:. python3 -m unittest test_ecd_snapshot test_core test_evolution test_global_account_plans test_global_fork_scopes test_account_plans test_plan_manager test_journal_query_loading test_journal_participants test_accounting_report_models test_report_models_api test_bulk_operations test_bulk_security test_operational_settings test_sped_generator test_sped_native_export test_sped_bookkeeping test_import_package_cleanup test_import_reprocessing test_reprocessing_linked_effects -q`. CI/infra: `PYTHONPATH=<dependências isoladas>:tests:scripts:. python3 -m unittest test_ci_release test_infrastructure -q`. AST dos quatro arquivos Python e diff-check passaram.

O contrato final da rota e seu ponto de registro foram conferidos com **76 testes SPED/ECD passando em 20,724 s**. Combinação local descartável com a PR43 (`3420f03`), sem conflito textual: **85 testes passaram em 21,550 s**, incluindo nove do catálogo e os 25 do snapshot. A PR43/branch base não foi modificada e não é dependência deste incremento. Não foram executados programa oficial ECD/PGE, assinatura/transmissão, navegador, PostgreSQL operacional, escala de produção, builds/instaladores ou suíte integral.

Próximo incremento: recuperar/confrontar a revisão maio/2026, fechar vigência/hierarquia/natureza das contas e contrato explícito de abertura por exercício, preservando o histórico observado. Depois preparar um recorte de serialização com faltas rastreáveis e ensaio sintético no programa oficial. Avisos não devem virar travas de exportação; suporte oficial completo só poderá ser declarado com cobertura e validação necessárias.
