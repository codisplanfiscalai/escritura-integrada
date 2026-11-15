# PR46: histórico de composição com develop

## Atualização atual: develop dev.16 / PR45

Head anterior: `3981b68295270968ebab4fbe62ec17185949e8f5`, com [CI150 aprovado](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43739344261). Nova develop incorporada: `c8339b3533306b8f7336da5bc71bf43faf852bc7`, dev.16, incluindo PR45 e release automática. Merge com dois pais, sem rebase nem reescrita do histórico.

Apesar da divergência informada no GitHub, a tentativa local com os heads remotos conferidos foi automática, sem conflitos textuais. Não houve resolução manual ou refatoração. `app/api.py`, `app/docker_updates.py`, executor, frontend e demais arquivos recebidos permanecem idênticos à develop. `app/permissions.py` preserva a exigência administrativa de `/api/docker-updates` e o caso ECD com `accounting.journals:export`; sua diferença contra a nova develop continua sendo apenas as duas linhas do caso ECD.

Os fontes de snapshot/registro ECD e seus testes, inclusive os cinco testes de composição diária/individual, são idênticos ao head anterior. Não há importação de código das PRs43/47. A PR47 continua no head `de78a732dc6ce3092aac9dd905abf75477e39f0c`, sem alteração por esta atualização. Somente este registro de evidências é atualizado além do merge da develop.

Validação local: a execução ampla tentou **344 casos em 163,238 s: 341 aprovados e três erros ambientais**, todos na criação de socket Unix temporário (`PermissionError: [Errno 1] Operation not permitted`). Os casos são `SocketBoundaryTests.test_invalid_and_oversized_socket_payload_fail_closed`, `test_real_socket_plan_and_job_round_trip` e `test_wrong_peer_uid_and_missing_socket_cannot_execute`. Não houve falha funcional ECD observada.

Repetição específica: **71 testes ECD/contabilização passaram em 36,194 s**; **18 testes FakeDocker/stubs sem socket passaram em 0,755 s**; **47 CI/infra passaram em 0,650 s**. São 388 casos distintos aprovados somando o conjunto amplo e CI/infra; os três casos de socket permanecem pendentes no executor. O harness local isolou apenas esses três nomes para a repetição dos 18; nenhum teste/skip ou configuração foi alterado no repositório/CI. O novo CI deve executá-los normalmente.

Comando amplo: `PYTHONDONTWRITEBYTECODE=1 ESCRITURA_DATA_DIR=<temporário> PYTHONPATH=<dependências isoladas>:tests:scripts:. python3 -m unittest test_ecd_daily_compatibility test_ecd_snapshot test_fiscal_sales_accounting test_fiscal_sales_composition test_docker_updates test_core test_evolution test_global_account_plans test_global_fork_scopes test_account_plans test_plan_manager test_journal_query_loading test_journal_participants test_accounting_report_models test_report_models_api test_bulk_operations test_bulk_security test_operational_settings test_sped_generator test_sped_native_export test_sped_bookkeeping test_import_package_cleanup test_import_reprocessing test_reprocessing_linked_effects -q`. CI/infra: `python3 -m unittest test_ci_release test_infrastructure -q` com o mesmo isolamento. Repetição dos 71: os quatro primeiros módulos do comando amplo. A suíte inclui os testes unitários do atualizador com `FakeDocker`, stubs de cliente/CLI e socket temporário sintético. Não houve conexão a daemon, pull real, instalação Docker, preparação de imagem real, corte ou alteração de containers.

AST de cinco arquivos, diff-check e identidade dos fontes contra ambos os pais conferidos. O snapshot continua parcial/somente leitura, sem saldo atestado ou promessa de ECD completa. Não executados navegador/frontend local, suíte integral, programa oficial ECD, PostgreSQL operacional, escala de produção ou builds/instaladores. Novo CI obrigatório antes do merge final; merge final, release e implantação ficam fora desta atualização.

## Composição anterior: develop dev.15

## Base, histórico e escopo

Head original da PR46: `73206ec21a935af7de855010e486d60a6719395a`, branch `feat/ecd-bookkeeping-snapshot`. CI anterior [43706383173](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43706383173) aprovado antes desta composição.

Develop recebida: `ebc310a9cedfaaf8bde052e15c9bd82af7d8a5ec`, dev.15, contendo as integrações das PRs39/42. Atualização por **merge com dois pais**, sem rebase, sem reescrever os commits existentes e sem merge final da PR na develop. O merge textual foi automático, sem conflitos.

`app/sped_generator/ecd_snapshot.py`, seu registro em `app/sped_generator/api.py`, testes anteriores e documento original da PR46 permanecem idênticos ao head original. A política de permissão mantém o caso ECD e recebe a rotina de integração contábil da develop. Frontend e fontes de contabilização, core, business e relatórios recebidos permanecem idênticos à develop.

Mudanças próprias desta atualização: cinco testes de composição e este registro de evidências. Nenhuma funcionalidade nova de ECD, regra fiscal, classificação, atestado ou schema foi acrescentada. PR43 não foi alterada. O head da PR47, `de78a732dc6ce3092aac9dd905abf75477e39f0c`, é preservado; sua composição posterior exige etapa própria.

## Matriz de compatibilidade sintética

| Caminho real recebido da develop | Conferência do snapshot |
| --- | --- |
| Geração individual | Duas notas produzem dois lançamentos; total observado de 10,03, sem duplicação. Relatório resumido permanece somente leitura e não cria lançamentos. |
| Geração diária, mesma classificação | Notas de 0,01 + 10,02 + 20,03 produzem um lançamento de 30,06 com duas partidas. Snapshot conserva os três vínculos atuais de documentos e o total uma única vez. |
| Estorno parcial de contribuição | Agregado original 30,06 permanece; compensação 10,02 entra na sua data. Débitos/créditos movimentados somam 40,08 e saldo líquido observado é 20,04 por lado. Não há marcação de estorno global inventada. |
| Repetição da geração | Repetição da intenção idempotente conserva os bytes do snapshot, sem nova contabilização. |
| Competência aberta/fechada/reaberta | Exportação de leitura conserva os bytes e o conteúdo lógico do banco. As políticas de escrita não são alteradas. |
| Empresa e intervalo | Empresa B não aparece no snapshot de A; lançamento de outubro aparece somente no histórico anterior, separado da movimentação de novembro. |

Os cenários de composição usam novembro/2026 sintético, para os serviços das PRs39/42. A referência ECD da PR46 permanece AC2025/janeiro2026: leitura de dados de outro exercício não acrescenta suporte oficial ou conformidade para esse período. Nenhum saldo ECD é atestado.

## Limite de rastreabilidade preservado

A PR39 registra o estorno parcial em auditoria própria, sem usar `journals.reversal_of` para afirmar estorno integral do agregado. O snapshot preserva esses campos como o domínio os mantém e lê ambas as partidas reais; não preenche um vínculo inexistente.

A API `fiscal-sales-accounting/journals/{id}/sources`, sob suas permissões contábil/fiscal, conserva as três contribuições e a reversão parcial. O contrato da PR46 continua explicitamente limitado a vínculos atuais de documentos/baixas, auditoria de lançamentos e referências de importação contábil. Depois do estorno, o documento revertido deixa o vínculo atual no agregado, mas sua contribuição histórica permanece na API específica. Não foram copiados payloads/modelos/notas dessa trilha para o snapshot nem ampliadas permissões. A incorporação integral dessa trilha ao artefato preparatório continua fora deste merge.

## Verificação

**370 testes distintos passaram:** 323 em 170,036 s, incluindo os cinco novos e as 318 regressões recebidas/existentes; mais 47 de CI/infraestrutura em 0,721 s.

Comando amplo: `PYTHONDONTWRITEBYTECODE=1 ESCRITURA_DATA_DIR=<temporário> PYTHONPATH=<dependências isoladas>:tests:. python3 -m unittest test_ecd_daily_compatibility test_ecd_snapshot test_fiscal_sales_accounting test_fiscal_sales_composition test_core test_evolution test_global_account_plans test_global_fork_scopes test_account_plans test_plan_manager test_journal_query_loading test_journal_participants test_accounting_report_models test_report_models_api test_bulk_operations test_bulk_security test_operational_settings test_sped_generator test_sped_native_export test_sped_bookkeeping test_import_package_cleanup test_import_reprocessing test_reprocessing_linked_effects -q`. CI/infra: `PYTHONPATH=<dependências isoladas>:tests:scripts:. python3 -m unittest test_ci_release test_infrastructure -q`. A primeira chamada específica detectou versão da configuração da empresa B incorreta na fixture; corrigida para a versão explícita da própria empresa, sem alterar a aplicação.

As leituras comparam SHA-256 do `iterdump()` integral antes/depois (todas as tabelas, auditoria, arquivos e BLOBs sintéticos). Repetição compara bytes, além de valores, IDs, sinais, competências e contadores de lançamentos/partidas. AST de quatro arquivos e diff-check conferidos. Provas dos fontes inalterados e da identidade das frentes recebidas foram feitas por diff contra os dois pais.

Não executados frontend/navegador local nesta atualização sem mudanças próprias de UI, suíte integral, PGE/ECD oficial, PostgreSQL operacional, escala de produção ou builds/instaladores. O novo CI precisa concluir antes do merge final. Somente fixtures sintéticas; sem documentos/planos/backups reais, produção, assinatura/transmissão, release ou implantação.
