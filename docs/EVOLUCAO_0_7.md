# Evolução 0.7 — diagnóstico e critérios

Base confrontada: develop 6130c3b (0.6.0-dev.7), main 438ffd6 (0.4.1). O histórico MHTML e o inventário dos 18 executáveis estão descritos em MATRIZ_RASTREABILIDADE.md. A origem adicional é auditorfiscal-1.2.2(1).zip, SHA-256 f738450837965543a190ac5304362abe868aee5dc9f35d19b8725a7dd6dbe2fb (MIT).

## Lacunas verificadas antes das alterações

| Fluxo | Evidência | Lacuna | Critério |
|---|---|---|---|
| Contexto anual | API check_period, ImportView, DocumentsView | Igualdade com mês global impede meses diferentes | Datas no ano selecionado, fechamento por mês/módulo, emissão preservada |
| Importação contábil | permissions.route_policy, Core.preview_import | Importador fiscal/bancário sem rotina contábil | Usuário somente contábil importa sem Fiscal; prévia e confirmação atômica |
| Auditor Fiscal | Motor Python do ZIP, Laravel/API e Vue anexos | Aplicação separada, serviços PostgreSQL/MinIO específicos | Mesmo login/RBAC; auditoria não grava documentos/títulos/partidas |
| Relatórios | Relatórios internos, Razão Caixa 08/2026 e formulários recuperados | Impressão genérica; nem todos os modelos possuem saída impressa | Catálogo diferencia reprodução comprovada, adaptação e falta de referência |
| Digitação | JournalView, DocumentsView, BaseModal | Salvar fecha; validação fixa mês | Salvar e novo, atalhos, preservação de erro, idempotência |
| Armazenamento | SQLite WAL único; FKs entre documentos/títulos/baixas/estornos | Arquivos sem organização anual; divisão física pode romper transações | Originais por empresa/ano/hash, backup íntegro e recuperação verificável |

## Decisão de persistência antes da migração

A base transacional permanece única nesta evolução. Os módulos utilizam chaves estrangeiras compostas por empresa, números estáveis e operações atômicas envolvendo vários anos. Separar fisicamente as tabelas por exercício removeria essas garantias: o SQLite não implementa FKs entre bancos anexados; transações em múltiplos arquivos em WAL não têm a mesma garantia de atomicidade em falha do host. Não serão criadas cópias anuais concorrentes dos cadastros.

Usuários, grupos, permissões, empresas e cadastros permanecem canônicos. Diretórios usam o ID estável da empresa, exercício e categoria. Arquivos imutáveis são identificados por SHA-256; os vínculos ficam no banco. O backup integral é a unidade recuperável que preserva os vínculos entre exercícios. Exportação/restauração isolada de um exercício exige primeiro resolver sua cadeia de dependências; não será apresentada como restauração independente sem essa garantia. A divisão física anual operacional permanece uma evolução de persistência, não uma migração silenciosa.

## Limites de evidência

O PDF de Razão Caixa permite comparação com uma saída real. Não há uma coleção de saídas impressas, com dados e filtros correspondentes, para todas as variantes dos 18 executáveis. Formulários/pseudocódigo comprovam campos e opções, não a aparência final de todos os relatórios. Os dados reais de referência não serão publicados no repositório.

O Auditor separa leitura, recálculo aritmético e validação normativa. Seus catálogos serão versionados e explicitamente publicados; nenhum catálogo recuperado será presumido vigente. O projeto original utiliza NFePHP. Nesta etapa, DANFE 55 foi substituído por BrazilFiscalReport 1.3.1 em Python e conferido com o XML sintético do projeto. NFC-e, DACTE, CT-e OS e DAMDFE ainda não possuem renderização habilitada/validada. Preservar um PDF importado não equivale a gerar ou validar um documento auxiliar. O módulo Social não possui leiautes de movimentações definidos no material disponível; não serão inventadas obrigações sociais.


## Recursos e rastreabilidade desta etapa

| Funcionalidade → origem | Implementação operacional | Validação / limite |
|---|---|---|
| Auditor Python → services/fiscal-engine/app do ZIP | app/auditor_engine; Decimal, documento/item/evento/duplicidade/conciliação de produtos | Motor adaptado; grupos especiais declarados sem recálculo normativo completo |
| Ciclo de análise → AnalysisController e audit_service do ZIP | app/auditor.py; fila persistida SQLite, retomada, cancelamento, reprocessamento em novo histórico, exclusão lógica/restauração | Testes de estado, isolamento, reprocessamento e ausência de efeitos fiscais/financeiros |
| Achados → modelos/controllers do ZIP | Evidência, regra/versão, severidade, responsável, tratamento e revisão concorrente | Resolver não muda origem; alterações na escrituração sinalizam auditoria desatualizada |
| Catálogos → catalog_import, CatalogController do ZIP | XLSX com prévia, NCM/EX, linhas herdadas explícitas, conflitos, origem preservada, JSON revisável, fonte/vigência/hash/publicação | Teste de exclusões explícitas e original; tabelas históricas do seed não ativadas nem presumidas vigentes |
| Relatórios Auditor → relatórios Python e ReportController | PDF/Excel, crítica, memória Decimal, documento e versão de origem, catálogo e logs | Exportação testada; custos/margens limitados à amostra, sem substituir estoque |
| Documentos auxiliares → NFePHP do ZIP | app/auxiliary.py, BrazilFiscalReport 1.3.1 | DANFE 55 sintético renderizado e inspecionado; demais modelos não certificados |
| Importação contábil/financeira → requisito operacional atual | module_imports.py + ModuleImportView; journals-v1, openings-v1, accounts-v1, titles-v1 | API testa usuário exclusivamente contábil, rejeição de outra empresa, equilíbrio, bloqueios, reenvio e seleção explícita |
| Exercício flexível → requisito atual | Contexto anual na API/Vue; fechamento continua por empresa/módulo/mês | Meses diferentes do ano aceitos; outro ano recusado; emissão anterior preservada |
| Salvar e novo → CTB020100, LFSDOCTOS e requisito atual | JournalView/DocumentsView/BaseModal; defaults opcionais, foco, atalhos e idempotência | Teste API de reenvio; roteiro de Chromium cobre sequência por teclado e erro preservado |
| Razão → PDF fornecido e CTB020400 | report_models.py + catálogo na interface; folha inicial, agrupamento, saldos, continuação | 403 movimentos importados via CSV, confirmados e persistidos; competência fechada consultada; 7 folhas e diferenças numéricas zero; tipografia/quebras ainda não idênticas |
| Arquivos → requisito atual | file_store.py; migração aditiva do índice dos originais, diretórios por empresa/ano/hash | Banco canônico contém originais; cópias de disco são reconstruídas e verificadas |
| Recuperação → requisito atual | snapshots.py; tela Sistema/Arquivos; Configurações do desktop | Snapshot online, integridade SQLite/FKs, contagens, totais monetários e hashes; restauração em destino novo |

## Contratos de importação

Os quatro novos CSVs são UTF-8, com separador `;`, datas ISO `AAAA-MM-DD` e valores decimais com ponto, sem expoente. A tela oferece o cabeçalho de cada versão. Em partidas, todas as linhas do mesmo ID pertencem ao mesmo lançamento; contas e centros usam seus códigos de acesso. Identificadores da origem devem ser estáveis e únicos por empresa no respectivo leiaute. Repetir a confirmação mantém o resultado; reutilizar uma identidade com conteúdo incompatível gera conflito. Plano de contas permite inclusão ou reconhecimento de cadastro idêntico; alterações de cadastro existente são feitas na rotina própria.

Cada lote tem arquivo original, prévia, hash, registros elegíveis/bloqueados/fora do exercício e seleção explícita. A confirmação dos selecionados ocorre em uma transação, com revalidação de permissões e bloqueios. Os recusados permanecem na prévia. Importar não cria efeitos financeiros implícitos. A auditoria avulsa usa sua própria entrada de arquivos e não passa pela escrituração.

## Auditor: cobertura e dependências

- Leitura: NF-e 55, NFC-e 65, CT-e 57, CT-e OS 67, MDF-e 58 e eventos NF-e; XML/PDF e ZIP. XMLs inválidos/empresa divergente ficam em achados. CT-e/MDF-e têm cobertura de leitura, sem apuração tributária.
- Aritmética: PIS/Cofins ad valorem com base/alíquota presentes; IBS/CBS regular; conferência assistida da fórmula UB16-10 recuperada. Não existe homologação de todos os cenários, vigências, regimes ou exceções. Grupos especiais não são recalculados como se fossem regulares.
- Parametrização: comparação NCM/EX × CST/cClassTrib com catálogo publicado pelo responsável. O importador XLSX verifica estrutura e consistência; não consulta a tabela oficial vigente. Condições/reduções/base legal recuperadas são preservadas como referência, sem aplicação automática de alíquota.
- Documentos auxiliares: BrazilFiscalReport 1.3.1 (LGPL-3.0) substitui NFePHP apenas no cenário DANFE 55 validado. `lxml` mantém o parser do motor original. Dependências transitivas e hashes estão no lock comum de Windows, macOS e Docker; avisos de terceiros acompanham a distribuição. Fontes: https://engenere.github.io/BrazilFiscalReport/ e https://github.com/Engenere/BrazilFiscalReport .
- Catálogos históricos do ZIP: manifesto 2025.10.03+classificacao-final, 15.638 linhas de parametrização, 142 cClassTrib e 19 CST. Permanecem material de referência, não tabela vigente embutida. As planilhas originais nomeadas pelo seed não constam no ZIP; existem JSONL compactados. Não foi feita substituição silenciosa dos parâmetros da escrituração.
- A fila integrada é local e persistida em SQLite, com executor de uma tarefa por vez, retomada e cancelamento cooperativo. Redis, PostgreSQL, MySQL e MinIO continuam infraestrutura opcional publicada, sem adaptadores operacionais neste núcleo.

## Backup e passagem de exercício

Sistema → Arquivos e backup permite ao administrador baixar um ZIP integral. No desktop, Configurações permite criar/restaurar backup. Restauração exige motor parado e diretório novo; os dados de origem nunca são sobrescritos. O pacote inclui o banco com usuários, grupos, permissões, empresas, cadastros, exercícios, documentos, vínculos, arquivos originais e auditorias; configurações externas do desktop (`config.ini`) não são parte desse ZIP de dados. A pasta restaurada deve ser aplicada em Configurações e o motor reiniciado.

O manifesto verifica integridade SQLite e FKs, quantidade por tabela, totais de documentos/partidas/títulos/baixas e SHA-256 dos originais. Diretórios dos arquivos são regenerados do conteúdo canônico. Saldos de relatórios incorporam movimentos anteriores ao intervalo; títulos podem vencer e ser baixados em outro exercício sem cópias divergentes. A abertura de novo exercício não gera encerramento contábil automático.

A opção técnica de manter uma única base transacional está apoiada em https://sqlite.org/lang_attach.html (limite de atomicidade entre arquivos em WAL) e https://sqlite.org/foreignkeys.html (referências não cruzam schemas). A divisão anual física e a restauração isolada dependem de resolver a cadeia completa de referências históricas.

## Validação e pendências concretas

A suíte local da etapa inclui testes de API para os fluxos acima e compilação Vue. `scripts/browser_evolution.py`, chamado pelo smoke Chromium existente, acrescenta validação de menu contábil exclusivo, lote misto, digitação contínua, erro preservado, auditoria interna/avulsa, DANFE e download de backup. Os resultados efetivos de navegador e distribuição são os relatórios do run de CI/release; presença do roteiro não significa execução bem-sucedida. O Chromium local desta sessão foi impedido de criar sockets pelo ambiente.

Permanecem: equivalência visual integral de todos os modelos Prosoft; saídas impressas correspondentes aos demais relatórios; renderizadores auxiliares além de DANFE 55; auditoria normativa integral e tabelas oficiais atuais; vinculação posterior explícita de auditoria avulsa; extração de XML de RAR/7z para auditoria interna (a importação fiscal existente continua suportada); armazenamento SQLite fisicamente anual com transações entre exercícios; restauração isolada com dependências; rotinas/importações Social ainda não especificadas. Os instaladores continuam sem Authenticode/Developer ID/notarização, conforme DISTRIBUICAO_DESKTOP.md.
