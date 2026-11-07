# Correção do Auditor Fiscal — 0.7.1

Base: `develop` 3650cb33463459f7310f730cb36a74239dea97a0 (0.7.0-dev.8). Projeto confrontado: `auditorfiscal-1.2.2(1).zip`, SHA-256 `f738450837965543a190ac5304362abe868aee5dc9f35d19b8725a7dd6dbe2fb`. Os fontes PHP, Python, Vue e os catálogos compactados foram lidos. A execução permanece em FastAPI/Vue, na mesma sessão e nas mesmas permissões do Escritura; nenhum serviço PHP foi acrescentado.

## Causas encontradas

1. A lista de inclusão do `.dockerignore` levava apenas `app/*.py`. A pasta do motor `app/auditor_engine/` ficava fora da imagem. Os testes antigos verificavam saúde/login do contêiner, sem executar uma auditoria.
2. Um lote totalmente recusado (por exemplo, CNPJ diferente da empresa selecionada) terminava como concluído, com zero documentos. Agora termina com falha explicada e relatórios de diagnóstico. Lotes mistos mostram cada recusa/duplicidade, sem inflar os totais.
3. O catálogo histórico não acompanhava a integração. O adaptador não carregava as referências de CST/cClassTrib. A interface não permitia revisar cada regra nem comparar versões.
4. O modo interno não oferecia seleção individual e deixava os registros sem XML fora da consulta de documentos. Faltava recuperar XMLs das origens ZIP aninhadas, RAR e 7z.
5. Relatórios eram produzidos sob demanda e sem histórico persistido dos arquivos. Algumas seções do original não estavam disponíveis em tabelas utilizáveis; valores monetários precisavam de células numéricas.
6. Progresso, conciliações, qualidade do catálogo e consulta dos itens estavam incompletos na interface. A geração de auxiliares só habilitava DANFE 55, embora a dependência Python já instalada também disponibilize DANFCE, DACTE e DAMDFE.

7. A janela desktop de impressão rejeitava links diretos de PDF. O Auditor agora usa o leitor Qt PDF já incluído no PySide6, com a mesma sessão local, visualização, salvamento e impressão; endereços externos não são aceitos. O smoke empacotado exige abertura de páginas PDF no leitor nativo.

## Matriz de migração e validação

| Recurso / origem no Auditor 1.2.2 | Implementação nativa | Critério e evidência automatizada |
| --- | --- | --- |
| AnalysisController / ProcessAnalysisBatch: criação, acesso, processamento, histórico | `auditor.py`, `auditor_api.py`, `evolution_api.py`, `AuditorView.vue`; fila persistida e retomada local; progresso por etapa/arquivo | Avulsa e interna, falha explícita, recuperação/reprocessamento em novo histórico, cancelamento, exclusão/restauração; `test_evolution`, `test_auditor_integration` |
| AnalysisAccess, CompanyAccess, TenantAccess | RBAC já existente por empresa, grupo e usuário; sem cadastro paralelo de tenants/clientes | Empresa estrangeira e ações não concedidas recusadas pela API; permissões refletem menus e botões |
| AnalysisResultValidator / Deduplicator | `auditor_results.py`, motor de duplicidades; identidades de documento/item e valores finitos | Duplicado não dobra documentos, itens ou total; originais e ocorrências preservados |
| Python xml_parser / decimal_utils / cross_rules | Motor em `app/auditor_engine`; memória Decimal, caminhos exatos dos tributos, recálculo aritmético | Casos originais de duplicidade/conciliação migrados; comparações de XML × escrituração; cenários especiais marcados como não recalculados |
| AnalysisAnalytics / ProductReconciliation | `analytics`, conciliação Python e tabela Vue | Quantidades, identidades, entradas/saídas, custos e margens estimados; ausência de dados não vira margem calculada |
| CatalogController / ImportCatalogSpreadsheet / seeds | `auditor_catalogs.py`, `AuditorCatalogs.vue`; importação XLSX, revisão, edição, exclusão, comparação e publicação imutável | 15.638 linhas, 11.096 NCMs completos, 19 CSTs e 142 classes; seis linhas com sete erros; publicação bloqueada até revisão |
| Finding / resolve | Tratamento com versão otimista, responsável, justificativa e auditoria | Resolver não corrige documento; evidência do resultado original permanece; relatórios anteriores preservados |
| XML e PDFs originais | Armazenamento compartilhado com SHA-256 e escopo empresa/exercício | Download byte a byte do original; PDF associado por chave ou vínculo manual justificado; arquivo de outro lote/empresa recusado |
| FiscalAuxiliaryDocumentGenerator (NFePHP) | `auxiliary.py`, biblioteca Python BrazilFiscalReport 1.3.1 já presente no lock | PDFs de modelos 55/65/57/58 gerados e abertos com fixtures sintéticas; CT-e OS possui espelho de conferência, com limitação abaixo |
| PDF/XLSX e memória | `auditor_reports.py`, `auditor_workbook.py`, `auditor_reports` no banco | Reabertura com pypdf/openpyxl; valores, códigos, seções e páginas conferidos; revisões e hashes persistidos |
| ApplicationLogger / logs/export | Logs de execução por auditoria + auditoria administrativa do Escritura; exportação NDJSON | Erros sem conteúdo sensível exposto; eventos relevantes com empresa, autor e data |
| Interface Vue original | Componentes nativos, mesma navegação e identidade do Escritura | Roteiro Chromium: importação → processamento → documento/item → tratamento → abertura de PDF/Excel; 1440 e 390 pixels |

A publicação não substitui retroativamente catálogos usados em auditorias. Cada trabalho guarda empresa, dados escriturados, XMLs, versão do motor e conteúdo/hash do catálogo. A edição da origem sinaliza necessidade de nova auditoria. Consultar/auditar competência fechada não a reabre.

## Operação

1. Auditor Fiscal → Auditoria avulsa: informe período/nome, escolha catálogo publicado quando aplicável, selecione XML/PDF/ZIP e inicie. Limite atual: 20 MiB por lote e limites de expansão; até 2.000 documentos internos por trabalho. Recusas ficam visíveis em Documentos.
2. Auditor Fiscal → Auditoria da escrituração: consulte o intervalo pela data de escrituração e selecione os documentos. Emissão anterior é preservada. Sem XML, os valores escriturados são consultáveis, com cobertura explicitamente limitada.
3. Abra Documentos para consultar itens, valores originais/escriturados/recalculados, baixar XML, gerar auxiliar ou associar PDF revisado. PDF não é fonte de cálculo.
4. Achados permite filtrar severidade/situação e registrar tratamento. Conciliação e margens apresenta as correspondências e estimativas da amostra.
5. PDF e Excel são produzidos no processamento. Relatórios oferece download, visualização/impressão e revisões anteriores. Falha na geração impede o estado de conclusão.
6. Catálogos → Importar referência 1.2.2 cria um rascunho histórico com todos os diagnósticos. Revise fonte, vigência e cada regra; nenhum erro é corrigido ou publicado automaticamente. O teste usa correções **sintéticas**, sem recomendar enquadramentos tributários.
7. Histórico permite reprocessar, excluir logicamente e restaurar com justificativa. A confirmação do reprocessamento mostra o catálogo de origem e permite escolher explicitamente outra versão publicada. Reprocessamento cria um novo retrato; não sobrescreve os resultados anteriores.

## Relatórios

Excel mantém as abas antigas e acrescenta Resumo Executivo, Notas Sintético, Itens Analítico, Tributos, IBS/CBS, Memória de Cálculo, Memória PIS/Cofins, Entradas × Saídas, Inconsistências, Duplicidades/Eventos, NCM/ClassTrib, Qualidade, Parametrização, Arquivos e Fontes. Valores são numéricos; NCM/chaves permanecem texto. Entradas capazes de virar fórmulas são gravadas como texto. O PDF inclui resumo, amostra/recusas, documentos/origens, comparação com escrituração, classificação, achados/evidências/tratamentos, memória, conciliação, eventos, catálogos e logs.

## Distribuições e persistência

Migração aditiva do esquema 4 para 5, concentrada no Auditor: progresso, referência/ancestralidade de catálogos, arquivos de relatórios e vínculos revisados de PDF. O mecanismo existente de backup/migração/recuperação permanece. Originais e resultados continuam no armazenamento do Escritura. Não foram introduzidos outro banco, outro login, Redis obrigatório ou MinIO obrigatório.

A atualização de um banco criado pelo código original 0.7.0-dev.8 foi executada localmente: backup automático, preservação do retrato/resultado antigo, abertura de relatório e reprocessamento sem alterar a escrituração.

Windows/macOS passam a processar uma auditoria e importar o catálogo histórico no smoke do aplicativo empacotado. Docker passa a criar empresa, auditar XML, conferir itens/totais/PDF/Excel/catálogo e validar persistência depois de reiniciar. Os mesmos fontes e dados de referência integram as três distribuições.

## Evidências e limites

Testes: `tests/test_auditor_integration.py`, `tests/test_auditor_original_*.py`, suíte existente, `scripts/browser_evolution.py`, `app/auditor_smoke.py`, `scripts/smoke_auditor.py`. Os relatórios de CI/release registram o SHA realmente testado. Scripts não são prova de execução; consultar o resultado do run correspondente à versão publicada.

- CT-e OS 67: leitura/auditoria e preservação de PDF disponíveis; o espelho Python não tem equivalência visual validada com o DACTE OS do NFePHP. Esta parte da paridade integral continua pendente.
- DANFE/DANFCE/DACTE/DAMDFE: geração funcional testada com fixtures sintéticas completas. Não houve homologação visual exaustiva contra todos os modelos/variantes NFePHP ou documentos de produção.
- Catálogos históricos têm edição 2025.10.03 e geração registrada em 2026-07-31. As planilhas-fonte citadas pelo manifesto não estão dentro do ZIP; os JSONL e hashes foram preservados. Atualização normativa e enquadramento fiscal exigem revisão. Nenhuma tabela histórica foi declarada vigente automaticamente.
- Recálculo aritmético não é auditoria normativa completa. Grupos especiais de IBS/CBS, regras condicionais e fórmula recuperada UB16-10 mantêm a limitação registrada no motor e nos relatórios.
- Não há migração automática de uma base de produção PostgreSQL do Auditor antigo: nenhum banco de produção foi fornecido. O projeto-fonte, não uma instalação produtiva, foi migrado.
- Assinatura Windows, Developer ID e notarização macOS permanecem ausentes. Certificação real SmartScreen/Gatekeeper e variantes de impressão dependem de material e credenciais próprios.
- Pendências mais amplas de Prosoft, armazenamento físico anual e Social continuam documentadas em `EVOLUCAO_0_7.md`; não são declaradas resolvidas por esta correção do Auditor.
