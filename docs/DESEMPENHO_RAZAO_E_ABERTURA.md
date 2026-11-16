# Diagnóstico local de abertura e relatórios

Base isolada: develop 0.9.0-dev.30, `2bc2051486afeba3612b31fb112c32f213328cc9`. Comparador: v0.8.0, `b5d97a354115310e278d3ce86308a48cc2824356`. Somente dados sintéticos descartáveis; nenhuma consulta ou alteração em produção. Não há AGENTS.md ou .agents/skills aplicáveis na worktree ou ancestrais examinados.

## Coordenação

Antes de editar, foram consultadas as PRs abertas 50 (prévia XML), 52/58 (backups) e 53 (atualização), e os arquivos das PRs 51 (Prosoft), 56 (cadastros/migração) e 57 (conferência NFC-e). A única mudança de aplicação é em `app/reports.py`, no bloco do Razão. Nenhuma alteração em DocumentsView, API, core, banco/migração, layout Prosoft, backups ou conferência NFC-e. A otimização de lançamentos da PR38 já está presente e não foi repetida. A PR50 toca a tela fiscal; a mudança de carga dessa tela foi deliberadamente deixada para coordenação separada.

## Causa comprovada e correção

No Razão, cada linha executava outra consulta de contrapartidas envolvendo a visão `effective_accounts`. Além disso, para cada conta analítica, a rotina percorria novamente todas as linhas para montar os grupos. Com 22.597 contas e 500 linhas do mês, o endpoint executou 512 SELECTs, incluindo middleware. O teste pequeno de seis linhas falhou antes da correção (10 SELECTs diretos em vez de cinco).

Agora uma consulta reúne as contrapartidas do intervalo e empresa, e um índice em memória agrupa as linhas por conta. A consulta de contrapartidas inclui todas as partidas dos lançamentos: filtros de conta, centro e pesquisa não podem eliminar a outra conta. A classificação continua sendo código único, `Diversos` ou vazio, com deduplicação. Mantêm-se saldos anteriores ao intervalo, saldos não recalculados pela pesquisa, estornos, ordenação, resposta e exportações. Não se alteram valores, regras fiscais, dados persistidos ou layouts.

## Método

`scripts/benchmark_report_loading.py`: 22.591 contas globais mais seis locais, 750 lançamentos (250 em setembro/2025, agosto/2026 e setembro/2026), 3.000 documentos (1.500 em agosto e setembro, cinco itens por documento), mais a pequena base demonstrativa. Uma execução de aquecimento e cinco amostras por rota. JSONs registram cada amostra, mediana, SELECTs, tamanho, quantidade e SHA-256 da resposta; fontes são identificadas por SHA e hashes. HTTP em processo/TestClient sobre SQLite; não mede rede real, carga concorrente ou produção. Rodadas comparativas são sequenciais; uma regressão pequena de 2,2 segundos também foi executada durante a rodada inicial, por isso diferenças pequenas não devem ser interpretadas como melhoria.

O navegador usa a mesma fixture em servidor de loopback e Chromium, sem limitação artificial de rede: cinco navegações frias após aquecimento por tela, com espera explícita pelas respostas de contas e movimentos, controles preenchidos e networkidle (inclui sua heurística de espera). Mede ainda geração do Razão até a resposta e tabela de 50 linhas. O tempo de abertura reúne servidor, transporte local, Vue e espera; não é decomposição pura de renderização.

## Custos ainda presentes

- A abertura fiscal solicita documentos anuais e contas completas: na fixture, 3.002 documentos / 5.991.092 bytes e 22.597 contas / 5.898.676 bytes. A consulta mensal retorna 1.500 documentos / 2.994.391 bytes. Não foi alterado o contrato da listagem.
- Relatórios contábeis também carregam o catálogo completo para escolher contas. O balancete inclui contas sem movimento: 20.544 linhas e aproximadamente 4,45 MB. Omitir essas contas mudaria o contrato, portanto não foi feito.
- A consulta de lançamentos do mês já se beneficia da PR38. Não há evidência aqui de uma nova regressão geral da dev.30; relatórios fiscais ganharam campos e regras desde 0.8.0, portanto tamanhos diferentes não significam perda nem equivalência funcional.
- O custo demonstrado do Razão também existe no código 0.8.0. Nenhuma dessas medições identifica, sozinha, a causa da lentidão na instalação do usuário.

## Resultados HTTP em processo

| Rota | v0.8.0 ms | dev.30 antes ms | correção ms | SELECTs antes → depois |
|---|---:|---:|---:|---:|
| `/accounts` | 477.628 | 499.126 | 576.358 | 10 → 10 |
| `/accounts?page=1&per_page=50` | 22.167 | 27.693 | 40.850 | 11 → 11 |
| `/documents?year=2026` | 1132.723 | 1154.590 | 1303.618 | 12 → 12 |
| `/documents?period=2026-09` | 485.056 | 560.797 | 611.646 | 12 → 12 |
| `/journals?year=2026` | 20228.702 | 65.800 | 80.209 | 11 → 11 |
| `/journals?period=2026-09` | 6734.407 | 49.248 | 92.602 | 11 → 11 |
| `/dashboard?period=2026-09` | 7.919 | 9.266 | 23.675 | 30 → 30 |
| `/business-reports/diary?start=2026-09-01&end=2026-09-30` | 48.314 | 46.926 | 83.292 | 11 → 11 |
| `/business-reports/ledger?start=2026-09-01&end=2026-09-30` | 9987.179 | 10519.570 | 189.373 | 512 → 13 |
| `/business-reports/trial-balance?start=2026-09-01&end=2026-09-30` | 486.546 | 561.869 | 567.345 | 12 → 12 |
| `/business-reports/fiscal-documents?start=2026-09-01&end=2026-09-30` | 166.483 | 172.511 | 213.125 | 11 → 11 |
| `/business-reports/fiscal-operations?start=2026-09-01&end=2026-09-30` | 219.615 | 206.189 | 268.608 | 11 → 11 |
| `/business-reports/ledger?start=2026-09-01&end=2026-09-30&format=csv` | 10207.055 | 10264.187 | 104.909 | 512 → 13 |

O Razão JSON e CSV, Diário, Balancete e ambos os relatórios fiscais medidos têm SHA-256 da resposta idêntico antes/depois da correção. Listas de documentos/lançamentos incluem timestamps da criação da fixture, portanto seus hashes não são comparadores estáveis entre bancos criados em horários diferentes. As pequenas diferenças de tempo nas rotas não modificadas não são tratadas como ganho/regressão. O ambiente compartilhado não garante ausência de carga externa.

Amostras completas: [v0.8.0](evidence/report-loading/v080.json), [dev.30 antes](evidence/report-loading/dev30-before.json), [correção](evidence/report-loading/dev30-after.json). No JSON pós-correção, o SHA identifica a base; o hash de `app/reports.py` identifica o arquivo corrigido durante a medição.

## Reprodução

```sh
python scripts/benchmark_report_loading.py --repetitions 5 --label before --output /tmp/before.json
python scripts/benchmark_report_loading.py --repo /checkout/v080 --source-sha b5d97a354115310e278d3ce86308a48cc2824356 --repetitions 5 --label v080 --output /tmp/v080.json
python scripts/benchmark_report_loading.py --repetitions 5 --label after --output /tmp/after.json
npm --prefix frontend run build
python scripts/browser_report_loading.py --output /tmp/browser-report-loading.json
PYTHONPATH=tests:scripts:. python -m unittest test_ledger_query_loading test_business test_report_models_api test_accounting_report_models test_journal_query_loading -q
```

Navegador requer Playwright e `ESCRITURA_TEST_BROWSER`; a execução local usa dependências isoladas em `/tmp`. O benchmark cria e remove apenas seus próprios diretórios temporários.

## Navegador integrado

Chromium 141.0.7390.37, mesma fixture e cinco amostras após aquecimento. Ambas as execuções finais terminaram com sucesso. A geração do Razão foi medida até a resposta completa e a tabela preenchida; as navegações incluem leitura integral do corpo pela instrumentação Playwright e espera de prontidão, portanto não são latência pura percebida pelo usuário.

| Fluxo instrumentado | dev.30 antes ms | correção ms |
|---|---:|---:|
| `fiscal_open` | 2621.293 | 2976.680 |
| `accounting_open` | 1180.335 | 993.042 |
| `reports_open` | 986.753 | 917.754 |
| `ledger_render` | 11803.857 | 241.835 |

A abertura fiscal/contábil e dos controles de relatório não foi alterada; oscilações de tempo nessas três linhas não são atribuídas ao patch. O ganho sustentado é a geração do Razão. No último traço após a correção, a abertura contábil ainda recebeu 5.898.676 bytes de contas, além de 466.495 bytes de lançamentos anuais; o filtro de setembro atua na interface. A tabela fiscal também recebeu os documentos anuais completos, apesar de exibir 50 registros por página.

Aceitação: Razão com 500 linhas e 50 por página, próxima página com registros distintos, CSV com todas as 500 linhas, pesquisa retornando duas partidas do lançamento selecionado, e hashes de documentos/lançamentos/partidas/títulos/auditoria iguais antes e depois da navegação. Nenhuma exceção de página capturada. Os filtros de conta, centro, empresa e exercício também foram conferidos nos testes backend; não se declara que todos foram exercitados no navegador.

As rodadas preliminares do medidor foram descartadas: uma usava seletor inadequado para o select envolvido em label; outra esperava networkidle da tela anterior; e o helper Response.finished do Playwright emitia avisos no encerramento. Os arquivos finais usam seletor por papel acessível, aguardam respostas explícitas e leem seus corpos, e foram reexecutados antes/depois com a mesma instrumentação.

Evidências finais: [antes](evidence/report-loading/browser-before.json) e [depois](evidence/report-loading/browser-after.json).

## Testes automatizados

Passaram 70 testes de backend e 184 de frontend, além do build Vite. O build conserva o aviso de bundle acima de 500 kB. O comando de backend executado foi:

```sh
PYTHONPATH=tests:scripts:. python -m unittest test_ledger_query_loading test_business test_report_models_api test_accounting_report_models test_journal_query_loading test_fiscal_analytical_reports test_fiscal_report_models test_fiscal_review_report test_export_performance -q
node --test frontend/tests/*.test.js
```

Os três testes novos cobrem consultas limitadas, comparação de contrapartidas com a consulta anterior, conta/centro/pesquisa, saldo anterior incluindo outro ano, empresa e competência vazias, restrição do exercício na API, partidas repetidas, estorno, ordenação, conteúdo integral do CSV e hashes persistidos. A primeira execução ampliada falhou em uma expectativa do teste novo que comparava diretamente o core com a API sem seus metadados já existentes de modelo; ajustado o teste, a suíte foi repetida e passou. Nenhuma alteração de comportamento da API foi feita.

Também passaram os scripts integrados existentes `browser_workspace_context.py` e `browser_document_summary.py` na base corrigida: indicadores fiscais/contábeis em agosto/setembro com novembro operacional preservado, empresa e exercício diferentes, outubro vazio, paginação, filtros combinados, navegação KeepAlive e atalhos F8/F9. Hashes de movimentos e auditoria ficaram intactos. Evidências: [contexto](evidence/report-loading/workspace-context.json) e [cartões](evidence/report-loading/document-summary.json).

## Limites

Sem homologação em dados reais, PostgreSQL operacional, rede do cliente, concorrência, instaladores ou layouts Prosoft reais. PDF/XLSX têm regressões funcionais nas suítes selecionadas, mas seus tempos de geração não foram medidos nesta rodada; a medição de exportação é CSV. Não foi executada a suíte integral do repositório nem CI remoto (não houve publicação). Não executados merge, release, deploy ou publicação externa. Este patch local aguarda coordenação de PR e revisão do novo CI quando houver publicação.
