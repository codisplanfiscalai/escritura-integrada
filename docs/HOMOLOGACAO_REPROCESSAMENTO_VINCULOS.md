# Homologação sintética de reprocessamento e vínculos

Execução local em 14/11/2026 no repositório `https://github.com/codisplanfiscalai/escritura-integrada.git`, confirmado por `git remote -v`. A branch `test/reprocessamento-vinculos-sinteticos` parte da `develop` real `92e0809342b749abc2421b035bf7e3266194250c` (0.9.0-dev.3), conferida por `git ls-remote origin refs/heads/develop` e `git fetch --no-tags origin refs/heads/develop`.

O worktree exclusivo é `/workspace/escritura-integrada-reprocessamento`. Não há `AGENTS.md`, `SKILL.md` nem `.agents/skills` nesse checkout ou instruções em `/workspace/.agents`. Foram lidos os fluxos de reprocessamento, classificação, grupos, financeiro e limpeza, os testes existentes, `docs/CORRECAO_IMPORTACAO_0_8.md`, o contrato de fixtures e as instruções de teste do README.

## Resultado funcional observado

Não foi demonstrado defeito funcional nos cenários exercitados. A suíte ampliada terminou com **112 testes aprovados**, incluindo os oito cenários novos. A mudança acrescenta oito testes em `tests/test_reprocessing_linked_effects.py` e este relatório. Nenhum código da aplicação ou bloqueio foi alterado.

O desdobramento testado altera as linhas fiscais de uma nota existente, mantendo o cabeçalho e os números dos itens. Não cria outra nota, outra fatura, outro título nem novos itens. Valores, impostos declarados, datas, identidades, IDs e fontes permanecem preservados. Isso não homologa o enquadramento dos CFOPs usados nos exemplos.

## Matriz executada dos oito testes novos

| Cenário | Comportamento efetivo | Evidência |
|---|---|---|
| Regra criada após importar | A regra nova não substitui automaticamente o CFOP gravado. A prévia conserva `1102` nos dois itens, com origem `existing_document`. Escolher explicitamente consumo para o segundo item aplica a regra `1556` somente nele. | `test_new_rule_preserves_existing_cfop_until_explicit_item_choice` |
| Desdobramento em múltiplos CFOPs com título XML aberto íntegro | Uma nota de 100,00 passa a ter linhas 1102/Revenda de 40,00 e 1556/Consumo de 60,00. O cabeçalho fica sem CFOP único. Conserva título, vencimento, valor, documento, fonte, itens, impostos e vínculos. | `test_split_multiple_cfops_preserves_open_xml_title_and_retry_identity` |
| Repetição | Mesma chave retorna `duplicate` sem nova versão, auditoria ou operação. Nova intenção, com prévia atualizada, pode registrar outra revisão fiscal, mas preserva IDs e não gera título adicional. | Mesmo teste do desdobramento, com `create_payables=True`, zero títulos criados e um preservado em cada confirmação |
| Grupo misturando CFOPs distintos | Bloqueado na prévia e na confirmação; resposta `reprocess_blocked`, sem nenhuma escrita. Separar grupos por item é uma escolha explícita. | `test_split_group_cannot_mix_cfops_and_block_is_atomic` |
| Baixa parcial e liquidação total | Uma baixa sintética de 40,00 e depois outra de 60,00 bloqueiam o reprocessamento. Prévia anterior à baixa retorna `reprocess_stale`; prévia nova identifica o bloqueio e confirmar retorna `reprocess_blocked`. | `test_partial_and_full_settlement_block_reprocessing_and_stale_preview` |
| Documento com `journal_id` | A contabilização posterior sintética mantém a nota, mas impede reprocessar. Mesmo sem incrementar a versão fiscal na contabilização, a prévia anterior fica desatualizada e não permite passar pelo bloqueio. Partida e linhas permanecem intactas. | `test_linked_journal_blocks_even_when_preview_precedes_accounting` |
| Título manual aberto | Estar aberto não basta. Um título manual vinculado não recebe o tratamento de segurança de um título XML íntegro; reprocessamento bloqueado, com preservação integral. | `test_manual_open_title_does_not_gain_xml_safe_reclassification` |
| Limpeza do pacote | Com limpeza permitida pelos parâmetros sintéticos, remover original e ocultar histórico mantém movimentos e origem normalizada. O original passa a retornar HTTP 410. Ainda é possível reprocessar pelo ID do lote com dados normalizados completos, sem upload, exclusão ou reimportação de notas. O XML permanece removido após a revisão. | `test_cleaned_original_keeps_normalized_reprocessing_and_financial_links` |
| Falha após alterar a segunda nota | Em lote com duas notas e dois títulos XML abertos, uma exceção simulada após atualizar a segunda nota desfaz toda a transação, incluindo a primeira revisão, vínculos, operações e auditoria. Repetir com a mesma prévia e chave funciona: zero notas novas, duas atualizadas, zero títulos novos e dois preservados. | `test_failure_after_second_document_update_rolls_back_links_and_can_retry` |

A conferência usa snapshots SQL de `documents`, `document_sources`, `titles`, `settlements`, `journals`, `journal_lines`, `bank_transactions` e `bank_allocations`. Nos cenários de bloqueio, repetição idêntica e rollback, compara também `imports`, `operations` e `audit`. A tentativa com duas notas chega a executar ambas as atualizações antes da falha; não é apenas uma rejeição antecipada de prévia. Depois da repetição, `PRAGMA foreign_key_check` não retorna violações.

Os testes existentes complementam a matriz com duplicatas de fonte, decisões conflitantes, regras ambíguas, destino por item, períodos fechados, permissão, versão concorrente, cancelamento e limpeza protegida/retida. Não foram removidas essas proteções para fazer os testes passarem.

## Comandos e resultados

Todos os comandos de teste foram executados no novo worktree. `ESCRITURA_DATA_DIR` isola a aplicação criada ao importar a API; cada caso também cria seu próprio banco temporário. As dependências declaradas de teste, instaladas na etapa anterior em `/tmp/escritura-financeiro-homologacao/python-deps`, foram reutilizadas sem modificar manifests ou o ambiente global.

1. Baseline:

   `ESCRITURA_DATA_DIR=/tmp/escritura-reprocessamento-homologacao/bootstrap ESCRITURA_DEMO=0 PYTHONPATH=/tmp/escritura-financeiro-homologacao/python-deps:tests python -m unittest test_import_reprocessing test_purchase_reclassification test_import_package_cleanup test_import_payables -v`

   Resultado: **65 testes, OK**, 35,433 s, saída 0. Log: `/tmp/escritura-reprocessamento-homologacao/baseline.log`.

2. Primeiros sete testes novos, antes de acrescentar o caso do título manual:

   `ESCRITURA_DATA_DIR=/tmp/escritura-reprocessamento-homologacao/bootstrap ESCRITURA_DEMO=0 PYTHONPATH=/tmp/escritura-financeiro-homologacao/python-deps:tests python -m unittest test_reprocessing_linked_effects -v`

   Resultado: **7 testes, OK**, 4,073 s, saída 0. Log: `/tmp/escritura-reprocessamento-homologacao/new-tests.log`.

3. Suíte ampliada, incluindo os oito casos novos:

   `ESCRITURA_DATA_DIR=/tmp/escritura-reprocessamento-homologacao/bootstrap ESCRITURA_DEMO=0 PYTHONPATH=/tmp/escritura-financeiro-homologacao/python-deps:tests python -m unittest test_reprocessing_linked_effects test_import_reprocessing test_purchase_reclassification test_import_package_cleanup test_import_payables test_fiscal_analytics test_generated_payables test_book_cancellation -v`

   Resultado: **112 testes, OK**, 45,589 s, saída 0. Log: `/tmp/escritura-reprocessamento-homologacao/focused.log`.

4. `git diff --check`: saída 0, sem diagnóstico. Nenhum workflow foi modificado.

Ambiente: Python 3.12.14, SQLite 3.53.1, FastAPI 0.141.1, Pydantic 2.13.4, httpx 0.28.1 e dependências de `requirements-test.txt`. O TestClient emite um aviso de depreciação de httpx, sem falha de teste. Os logs ficam fora do Git.

## Limites e próximos passos

- Esta é homologação sintética de API e domínio sobre SQLite local. Não valida DIX, produção, PostgreSQL real, documentos autorizados, XSD, assinatura, enquadramento fiscal, paridade Prosoft ou PVA. A transformação de `tpAmb` no helper existe apenas nos XMLs fictícios, para exercitar a rotina.
- Não foram executados pagamentos reais. As duas baixas e o lançamento contábil citados são dados de teste criados por API em bancos temporários, para conferir o bloqueio e sua integridade.
- Título XML aberto íntegro e título manual aberto têm comportamentos diferentes. A ampliação para títulos liquidados ou documentos contabilizados requer um fluxo que resolva as referências financeiras/contábeis; retirar a validação não seria uma correção segura.
- Reclassificação após limpeza foi testada por API com dados normalizados completos. Não comprova jornada de interface para localizar lote oculto, renderização de DANFE após remoção, nem recuperação de cobrança legada ausente do JSON e sem XML original.
- Próximo passo sugerido: conferir a jornada de seleção/revisão de grupos no navegador com as mesmas fixtures e decidir explicitamente se o produto deve oferecer reaplicação de novas regras sobre CFOPs gravados. A rotina atual exige nova escolha explícita e preserva a decisão existente por padrão.
- Não foram executados suíte integral, frontend, builds, CI remota, merge, release ou implantação. Não houve push ou abertura de PR. A PR 28 e sua branch `test/financeiro-sintetico-fat-dup` permanecem no head `c7858e799298987bdbb1aa11d0f7ca4563d7a644`; Atlas e integrações ficaram fora do trabalho.
