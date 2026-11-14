# Homologação sintética de faturas e contas a pagar

Execução local em 14/11/2026, sobre `develop` em `ecae8f377c84334ac57914df9cc2a0b251f99159`, confirmado por `git ls-remote origin refs/heads/develop`. Repositório: `https://github.com/codisplanfiscalai/escritura-integrada.git`. Branch local: `test/financeiro-sintetico-fat-dup`.

O checkout foi criado em `/workspace/escritura-integrada-financeiro`. O projeto pré-carregado, `escrituracao-contabil`, é outro repositório e permaneceu intacto. Não foram encontrados `AGENTS.md`, `.agents/skills` ou `SKILL.md` no repositório alvo. Foram consultados o fluxo existente, seus testes, `docs/CORRECAO_IMPORTACAO_0_8.md`, `tests/fixtures/README.md` e a configuração de CI.

## Resultado e alterações

Não foi comprovada falha funcional no fluxo financeiro exercitado. A execução final passou em **97 testes Python** (incluindo os **39 testes diretamente dedicados a cobrança XML e geração de parcelas**) e **22 testes de interface**. Foram acrescentados cinco testes para cobrir lacunas de homologação, sem alterar código da aplicação:

- `tests/test_generated_payables.py`: prazo padrão real de 30 dias com emissão/chegada independentes da escrituração; filtro por CNPJ formatado em lote misto; coexistência das opções XML e regra alternativa; repetição de reprocessamento com novas chaves.
- `tests/test_import_payables.py`: falha simulada na criação da segunda duplicata após a primeira escrita, rollback integral e nova tentativa bem-sucedida.
- Este relatório registra a matriz, os comandos e os limites da execução.

## Matriz de cobertura executada

Os nomes abaixo são métodos de teste nos arquivos indicados. Todos usam dados sintéticos e bancos SQLite temporários.

| Comportamento | Evidência executada | Resultado esperado conferido |
|---|---|---|
| FAT, desconto e líquido; duas DUP | `test_xml_billing_parser.py`: `test_preserves_header_discount_and_two_installments` | Campos originais e parcelas preservados |
| Números, valores, datas e vínculo à entrada/empresa | `test_import_payables.py`: `test_explicit_billing_creates_linked_titles_only_once`, `test_multiple_installments_preserve_numbers_dates_and_values` | Títulos vinculados, sem baixas; 40 + 60 = 100 |
| Ausência de cobrança e opção desligada | `test_missing_billing_is_not_an_error_even_for_unidentified_nfce`, `test_reprocessing_with_new_keys_preserves_generated_title` | Sem parcelas inventadas na importação fiscal inicial |
| Prazo padrão por emissão ou entrada efetiva | `test_generated_payables.py`: `test_default_thirty_days_uses_chosen_basis_and_keeps_document_link` | Emissão 05/11 → 05/12; chegada 10/11 → 10/12; escrituração 20/11 não muda a base; `term_days` omitido resulta em 30 |
| Entrada ausente, base explícita e prazo configurável | `test_date_basis_must_be_explicit`, `test_receipt_explicit_and_independent_from_posting` | Ausência bloqueia; chegada 10/11 + 45 dias → 25/12 |
| Seleção de notas e filtro por CNPJ formatado | `test_issue_default_thirty_and_idempotency`, `test_supplier_filter_in_mixed_batch_never_replaces_incomplete_billing` | Duas notas do CNPJ escolhido geram duas parcelas; outro fornecedor não gera |
| FAT incompleta ou DUP inválida não recebe regra alternativa | `test_supplier_filter_in_mixed_batch_never_replaces_incomplete_billing` | Cobrança original permanece; nenhuma parcela substituta |
| XML e regra alternativa habilitados no mesmo lote | `test_xml_and_generated_options_coexist_without_duplicate_titles` | Uma nota com título XML e outra com título por regra, com origens distintas |
| Reimportação, arquivo renomeado e confirmação repetida | Testes de idempotência XML, regra e lotes mistos | Nenhum título adicional; IDs e títulos preservados |
| Geração posterior repetida com novas chaves | `test_reprocessing_with_new_keys_preserves_generated_title` | Três confirmações: uma criação, depois duas preservações do mesmo título |
| Atomicidade após uma escrita financeira | `test_failure_creating_second_installment_rolls_back_and_can_retry` | Falha deixa zero documentos/títulos/baixas; lote segue em prévia; repetição cria uma entrada e duas parcelas |
| Permissão, período fechado e natureza não reconhecida como compra | `test_permission_denial_rolls_back_fiscal_and_is_visible_in_preview`, `test_financial_permission_and_closed_period_roll_back`, `test_non_purchase_and_missing_selection_block` | Bloqueio visível, sem importação parcial |
| Legados, divergências e títulos protegidos | Testes de recuperação do original, reprocessamento, revisão e cancelamento da suíte ampliada | Sem regeneração silenciosa; cobrança divergente exige revisão |
| Geração somente XML preserva a escrituração | `test_billing_only_preserves_fiscal_rows_and_generates_183_linked_installments` | 59 notas sintéticas, 183 títulos; nenhuma coluna fiscal regravada; repetição sem duplicar |
| Interface de revisão e confirmação | `frontend/tests/import-review.test.js`, `frontend/tests/import-workflow.test.js` | Opções desligadas inicialmente, base explícita, permissões, hashes e confirmação de cobrança |

## Comandos e evidências locais

Executados na raiz do checkout, salvo a instalação npm. Logs em `/tmp/escritura-financeiro-homologacao/`; não contêm dados de produção e não foram adicionados ao Git.

1. Baseline: `ESCRITURA_DATA_DIR=/tmp/escritura-financeiro-homologacao/bootstrap ESCRITURA_DEMO=0 PYTHONPATH=tests python -m unittest test_xml_billing_parser test_import_payables test_generated_payables -v` → **34 testes, OK**, 13,344 s, saída 0 (`baseline.log`). Antes de definir o diretório isolado, a importação da aplicação falhou por diretório padrão somente leitura; nenhum teste foi executado nessa tentativa.
2. Quatro primeiras regressões isoladas: `ESCRITURA_DATA_DIR=/tmp/escritura-financeiro-homologacao/bootstrap ESCRITURA_DEMO=0 PYTHONPATH=tests python -m unittest test_generated_payables.GeneratedPayablesTests.test_default_thirty_days_uses_chosen_basis_and_keeps_document_link test_generated_payables.GeneratedPayablesTests.test_supplier_filter_in_mixed_batch_never_replaces_incomplete_billing test_generated_payables.GeneratedPayablesTests.test_reprocessing_with_new_keys_preserves_generated_title test_import_payables.ImportPayablesTests.test_failure_creating_second_installment_rolls_back_and_can_retry -v` → **4 testes, OK**, 2,093 s, saída 0 (`regressions.log`). O quinto teste foi incluído na suíte ampliada.
3. Primeira suíte ampliada: `ESCRITURA_DATA_DIR=/tmp/escritura-financeiro-homologacao/bootstrap ESCRITURA_DEMO=0 PYTHONPATH=tests python -m unittest test_xml_billing_parser test_import_payables test_generated_payables test_fiscal_import test_import_reprocessing test_import_revision test_book_cancellation -v` → **97 testes, 1 falha**, 44,676 s, saída 1 (`focused.log`). A falha foi no teste de DANFE sintético, com `ModuleNotFoundError` e HTTP 422: `BrazilFiscalReport` não estava instalado no runtime inicial. Todos os testes de FAT/DUP e geração de parcelas passaram.
4. Dependências declaradas, isoladas: `python -m pip install --target /tmp/escritura-financeiro-homologacao/python-deps --cache-dir /tmp/escritura-financeiro-homologacao/pip-cache -r requirements-test.txt` → saída 0 (`pip-install.log`).
5. Reexecução ampliada: `ESCRITURA_DATA_DIR=/tmp/escritura-financeiro-homologacao/bootstrap ESCRITURA_DEMO=0 PYTHONPATH=/tmp/escritura-financeiro-homologacao/python-deps:tests python -m unittest test_xml_billing_parser test_import_payables test_generated_payables test_fiscal_import test_import_reprocessing test_import_revision test_book_cancellation -v` → **97 testes, OK**, 46,461 s, saída 0 (`focused-pinned.log`). A falha de renderização da tentativa anterior foi resolvida pela instalação das dependências, sem mudança da aplicação.
6. Em `frontend`: `npm ci --ignore-scripts --cache /tmp/escritura-financeiro-homologacao/npm-cache` → saída 0, 36 pacotes instalados (`npm-ci.log`). A tentativa inicial sem `--cache` falhou por cache padrão indisponível, saída 254.
7. `node --test frontend/tests/import-review.test.js frontend/tests/import-workflow.test.js` → **22 testes, 22 passaram, 0 falhas**, 1.551,619 ms, saída 0 (`frontend.log`).
8. `git diff --check` → saída 0, sem diagnóstico.

Ambiente: Python 3.12.14, SQLite 3.53.1, Node 24.22.1, npm 11.9.0. Na reexecução: FastAPI 0.141.1, Pydantic 2.13.4, httpx 0.28.1, ReportLab 5.1.0, lxml 6.0.2, pypdf 7.0.0 e BrazilFiscalReport 1.3.1. O aviso de depreciação de `httpx` no TestClient permaneceu informativo.

## Limites e próximos passos

- Homologação local de API/domínio em SQLite e componentes Vue com mocks; não houve PostgreSQL real, browser integrado, homologação SEFAZ, validação XSD/assinatura nem teste de produção. A suíte completa do projeto, builds e CI remota não foram executados.
- As fixtures são fictícias; o helper existente troca `tpAmb` para 1 apenas nos bytes sintéticos para exercitar a escrituração. Isso não é evidência de autorização fiscal real.
- Os novos testes não chamam endpoints de pagamento ou baixa. Alguns testes existentes exercitam baixas e partidas exclusivamente sintéticas em bancos temporários. Nenhuma DIX, título real ou banco de produção foi acessado.
- Não houve push, PR, merge, release, implantação, escrita remota ou alteração de versão. As PRs 24–27, a frente de integrações/PostgreSQL, a PR Atlas e a versão estável 0.9.0 ficaram fora do trabalho.
- Próxima etapa possível: revisar o commit local e, somente em trabalho separado autorizado, validar em banco PostgreSQL descartável quando esse backend estiver disponível e executar a jornada completa no navegador com as mesmas fixtures. Publicação exige a conferência prévia das ações pendentes e autorização correspondente.
