# Subguias de exportação Prosoft

Base atual verificada: `origin/develop` em `4f53d1a0b52fc7c0edffd744bc259128863259e2` (0.9.0-dev.33). A implementação inicial foi validada em dev.32 e recomposta sem conflitos sobre dev.33 para a PR em rascunho. Implementação frontend isolada; sem alteração de API, regras fiscais/contábeis, permissões, workflows ou dados reais.

## Organização implementada

As duas áreas de `ProsoftView` usam três subguias:

- **Exportação e prévia**: gerar, conferir totais, avisos/não exportados, origens e conversões, confirmar e baixar. A configuração salva é reutilizada sem etapa obrigatória intermediária.
- **Configuração e mapeamentos**: empresa/plano do destino, lote, espécies/CFOP ou contas/CTA/centros/terceiros, busca, paginação e salvar/recarregar. Recarregar uma edição não salva permite cancelar o descarte.
- **Cobertura e limites**: limites dos perfis e layouts ainda indisponíveis. Avisos específicos do lote permanecem junto à prévia e à confirmação.

Empresa, destino, versão, tipo e competência ficam fora dos painéis, visíveis em todas as subguias. Links de revisão levam à configuração, inclusive no erro. As abas usam `tablist`, `tab`, `tabpanel`, associação de IDs, seleção anunciada e foco móvel com setas/Home/End; Tab entra no painel. O componente reaproveita cores e fonte do aplicativo e quebra a faixa em telas estreitas.

Os painéis usam `v-show`: mudar de subguia mantém campos, busca, filtros e prévia. O controlador original permanece sem alterações: editar configuração ou mudar contexto invalida prévia/download e respostas atrasadas. Rascunhos não salvos continuam sujeitos ao comportamento existente de encerramento/reload; sair da página e voltar recupera somente configurações persistidas. Não há nova persistência em armazenamento do navegador.

## Inventário das views revisadas

Revisão de estrutura no código, sem declarar QA funcional de telas não modificadas:

| View | Decisão nesta frente |
|---|---|
| ProsoftView, fiscal e contábil | Implementadas três subguias, contexto comum e atalhos de revisão. |
| ReportsView | Colisão direta com a padronização `75fccdf3c1ebf75f02645ed797f24bed50fb6307`; diff lido, nenhum conteúdo incorporado. Proposta posterior: seleção/filtros e resultado no fluxo principal; catálogo/evidências em subguia, mantendo PDF/Excel/CSV e limites junto do resultado. |
| DocumentsView | Preservada por conflito com PR50; filtros, tabela e prévia fiscal não alterados. |
| AuditorView | Já oferece seções de análise, histórico, achados e relatórios; sem duplicar navegação. |
| ImportView | Fluxo de seleção/prévia em modal e histórico com detalhes expansíveis; mantido. |
| ModuleImportView | Upload, prévia e histórico são etapas do mesmo fluxo; possível separar histórico futuramente, sem impor abas agora. |
| FiscalSalesAccountingView | Seleção, prévia e resultado ligados à operação; configuração atual em detalhes; preservada nesta frente independente. |
| MastersView | Cadastros e editores específicos; não acrescentadas abas artificiais. |
| JournalView | Rotinas de lançamentos/plano/centros já separadas pelo menu e seção. |
| FinanceView | Pagar, receber e baixas já separados por rotina, com filtros e exportação próprios. |
| AssessmentsView | Tributo/competência e memórias/finalizações/ajustes relacionados; sem esconder pendências. |
| ReconcileView | Extrato e conferência precisam permanecer juntos para conciliar. |

Relatórios em todos os módulos **não foram reorganizados nesta entrega**: a continuação depende da coordenação com a frente de padronização. Esta PR não incorpora nem publica o conteúdo daquela frente. O checkout informado pelo coordenador não estava presente; o objeto Git do commit estava disponível e permitiu ler o diff sem fetch/publicação adicional.

## Verificação e limites

- `npm --prefix frontend run build`: passou; permanece aviso Vite de chunk acima de 500 kB.
- `node --test frontend/tests/*.test.js`: 193 passaram, nenhuma falha/skip. Inclui novo teste de preservação de estado ao alternar subguias e cancelamento da recarga.
- Na primeira rodada, dois testes de montagem falharam por import relativo do novo componente em módulo `data:`; o harness foi atualizado para componentes filhos, e a suíte completa passou.
- `scripts/browser_prosoft_export.py`: **passou**, 13 grupos de verificação, Chromium 141.0.7390.37, nenhum erro JavaScript; banco SQLite temporário e empresas/documentos fictícios; não utiliza imagens/dados privados como fixtures. Gera relatório JSON e capturas locais em `artifacts/browser-prosoft-export/`.
- A ampliação de fechamento inicialmente usou o rótulo “Cancelar”; o diálogo existente chama essa ação “Voltar”. O seletor foi corrigido e o ensaio completo passou.
- O ensaio confere prévia, ZIP/TXT/mapa baixados, posições dos registros, totais, perfis com/sem CTA, repetição da confirmação, contexto/latência, buscas, teclado, recarga cancelada, fechamento e histórico do navegador. Compara hashes das tabelas econômicas antes/depois.
- Capturas sintéticas desktop 1440 px e móvel 390 px foram inspecionadas visualmente. As referências privadas fornecidas foram inspecionadas localmente e não foram copiadas para o repositório.
- Não executados: homologação no Prosoft real, backend completo, PostgreSQL, outros navegadores, instaladores ou CI remoto. O ensaio sintético não é homologação real. A publicação autorizada desta frente é somente em PR draft. Não houve merge ou implantação.

Reprodução local: build frontend, dependências Python de teste e Playwright/Chromium disponíveis, seguido de `PYTHONPATH=. python scripts/browser_prosoft_export.py`. `ESCRITURA_TEST_BROWSER` permite escolher o executável Chromium instalado. O ambiente usado disponibilizou dependências previamente instaladas em diretório externo; nenhum lock/requisito foi alterado.


Evidências locais da versão final (somente dados sintéticos):

- `artifacts/browser-prosoft-export/report.json` — resultado e verificações.
- `artifacts/browser-prosoft-export/fiscal-operation-desktop.png` — operação compacta.
- `artifacts/browser-prosoft-export/fiscal-settings-desktop.png` — configuração fiscal.
- `artifacts/browser-prosoft-export/accounting-settings-desktop.png` — configuração contábil.
- `artifacts/browser-prosoft-export/accounting-operation-mobile.png` — 390 px.
- Prévia fiscal/contábil, capturas móveis e downloads sintéticos também permanecem nessa pasta ignorada pelo Git. Reexecutar o script regenera as evidências; as imagens privadas de referência não fazem parte delas.

A recomposição autorizada sobre dev.33 mantém somente cinco arquivos próprios: esta documentação, `SectionTabs.vue`, `ProsoftView.vue`, o harness/teste em `period-views.test.js` e `browser_prosoft_export.py`. Relatórios, padronização visual pendente, DocumentsView/PR50, backend, manifests e workflows permanecem idênticos à base. O patch separado de performance não foi incorporado. A situação do CI deve ser consultada na PR para seu head exato; aprovação local não substitui o CI remoto.
