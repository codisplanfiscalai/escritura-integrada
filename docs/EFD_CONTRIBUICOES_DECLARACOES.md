# EFD-Contribuições referências e declarações somente leitura

**Registro histórico dev.20, não o HEAD desta composição:** continuação local do diagnóstico, transportada sem alterar o worktree anterior para `feat/contributions-declarations-local`, base develop dev.20 `87b913990d8dc6160734c5b1f8046f6af9feb44f` (PRs46/47/48/41 já integradas). PR43 e outras branches permanecem fora desta alteração. Não há commit novo, publicação ou implantação. A revisão é de preparação; não calcula tributos, reconhece créditos, escolhe regime ou produz EFD.

**Composição posterior atual:** este checkout foi primeiro composto em dev.26 e depois
em dev.27, com PR43/44/57 e PR51 já integradas na base. O worktree e as evidências dev.20
permanecem preservados. Veja
[EFD_CONTRIBUICOES_COMPOSICAO_DEV26.md](EFD_CONTRIBUICOES_COMPOSICAO_DEV26.md).
As afirmações de base/execução históricas abaixo não são CI ou homologação do novo head.

O snapshot passa ao schema_version 2 com `preparation_review`. Os campos documentais anteriores e `unattested` permanecem preservados. As declarações ficam em seção própria; `resolved_company_fields` continua null e `classification_applied` false mesmo quando os códigos declarados constam das fontes conferidas. Não há propagação automática para documentos/itens.

## Referências temporais verificáveis

O catálogo `app/data/contributions-reference-catalog.json` contém seis artefatos públicos recuperados e confrontados em 16/11/2026. A revisão interna do contrato `contributions-2026-11-review-20261116` é um identificador de observação do conjunto, não uma data de vigência oficial. O recorte conferido para revisão de códigos é **2026-11**. Competências anteriores/posteriores e IDs desconhecidos não recebem fallback para a referência mais nova. A consulta documental continua exportável com avisos.

| Artefato oficial | Revisão declarada/conteúdo | SHA256 dos bytes recuperados | Vigência não presumida |
| --- | --- | --- | --- |
| [Guia Prático](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/manuais/guia_pratico_efd_contribuicoes_versao_1_35-18_06_2021.pdf/@@display-file/file), 4.105.830 bytes | 1.35, 18/06/2021; tabela p.57: código 006 / 3.2.0, início janeiro/2020; campos 0110 p.71 | `60eace459169238808e3e745e952fcbbbd2af6b7f933b043e8c9692b68f4d08b` | Fim oficial do leiaute não deduzido; alterações posteriores ainda exigem confronto por finalidade |
| [NT11/2026 atual](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/documentos-tecnicos/nota-tecnica-11-2026-descontinuidade-da-efd-contribuicoes-orientacoes-para-os-contribuintes/@@display-file/file), 86.320 bytes | 11/2026, três páginas legíveis | `1eca9b37057ba71989e0813dc112df0b578e3ce74d44099f81b2c4f554202130` | Dia da revisão interna desconhecido; timestamp do portal não o substitui |
| [NT12/2026](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/documentos-tecnicos/nota-tecnica-12-2026-reducao-linear-de-incentivos-e-beneficios-lc-224/@@display-file/file), 224.526 bytes | 12/2026; trecho de ajustes da página 1 | `9ff91fc533ae9a7c5865dde4939dbcda717287fec2f7bf5b24af0a931b35b91b` | Não implementa redução de benefícios, alíquotas, créditos ou seus cálculos |
| [NT13/2026](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/documentos-tecnicos/nota-tecnica-013_2026-alteracoes-efd-contribuicoes-para-rtc-2027.pdf/@@display-file/file), 346.724 bytes | 13/2026; trecho de 2026 e transição 2027 da página 1 | `5b588eb7a49581a4073eaaad1e1ad2c73f18781fa90fb5e46439eaaab6c1c5b1` | Transição a partir de 2027 é aviso de escopo, não implementação nem encerramento geral da obrigação |
| [Tabela CST-PIS 4.3.3](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/tabelas-de-codigos/tabelas-utilizadas-na-apuracao-das-contribuicoes-para-o-pis-pasep-e-da-cofins/tabela-4-3-3%20/@@download/file), 44.544 bytes | 1.0.0; 33 códigos extraídos de células de texto | `9fc93da5feca352592b4829ef1a586ae23baad4f441f7d3d1be711de7712a61b` | Datas inicial/final e dia da revisão não atestados: null |
| [Tabela CST-Cofins 4.3.4](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/tabelas-de-codigos/tabelas-utilizadas-na-apuracao-das-contribuicoes-para-o-pis-pasep-e-da-cofins/tabela-4-3-4%20/@@download/file), 44.544 bytes | 1.0.0; 33 códigos extraídos de células de texto | `e360d38bec4f985447563cb02fd3f96ce86a8fa03a428c0d57f94b17f7f790f8` | Datas inicial/final e dia da revisão não atestados: null |

Os três PDFs já recuperados na etapa anterior mantiveram os mesmos hashes. A NT11 foi recuperada do recurso atual do gov.br; versões históricas alternativas não foram reconstruídas. Os arquivos Word legados são OLE, com tabela de texto CP1252 contígua identificada pelo título e delimitadores de célula; cada tabela produziu 33 códigos distintos. Não foram executadas macros, conversões fiscais ou importadores de documentos Word no runtime. O código armazena apenas os códigos e seus descritores, não os binários ou descrições integrais.

Os links reais das duas tabelas foram localizados no estado público embutido no HTML do [catálogo oficial](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/tabelas-de-codigos/tabelas-utilizadas-na-apuracao-das-contribuicoes-para-o-pis-pasep-e-da-cofins), inclusive o espaço final codificado `%20`. O HTML observado tem SHA256 `3ac48de10ee1564ece941fe0e029964c593d46abf74d3e6cce82e1e71a998ebd`; esse hash representa a resposta observada, não assinatura permanente. Seu timestamp de migração em 1969 não é utilizado como vigência fiscal. Arquivos históricos ausentes e datas desconhecidas não são preenchidos com datas presumidas.

O catálogo não cobre integralmente tabelas de benefícios, atividades, alíquotas ou históricos de créditos; `historical_artifacts_complete` e `publisher_signature_verified` são false. A seleção fixa inclui hashes dos artefatos e SHA256 canônico próprio; adicionar uma revisão futura não muda uma seleção histórica pelo ID anterior. Não há download de rede durante a consulta. A retenção dos binários por revisão fora do código ainda precisa de solução própria.

## Classificação explicitamente declarada

A leitura usa somente a chave opcional `data.contributions_preparation_v1` dos cadastros de estabelecimento, produto e serviço existentes. O namespace é uma **lista** de declarações; não há tabela nova, migração, nova rota de escrita, editor ou mecanismo que gere essas declarações a partir do XML/cadastro genérico. A API cadastral existente já preserva esses dados adicionais; os testes criam apenas fixtures por esse caminho.

| Campo do contrato | Tratamento |
| --- | --- |
| id e revision | Textos explícitos e canônicos; par id/revision identifica a declaração na empresa, não é escolhido pela data mais recente |
| company_id | Inteiro explicitamente igual à empresa proprietária do cadastro; bool e outra empresa geram diagnóstico |
| scope | company em estabelecimento; item em produto/serviço. Nenhuma regra é deduzida do nome/código do cadastro |
| direction | incoming/outgoing obrigatório para item; não se usa both como padrão nem se converte CST de saída em entrada |
| valid_from/valid_to | Competências explícitas AAAA-MM, ambas presentes e ordenadas; consulta inclusiva; sem fim aberto presumido |
| reference_id | ID exato do catálogo; ausência/desconhecido/ambíguo/fora do período conferido não selecionam outra revisão |
| source/source_sha256/responsible/declared_on | Referência documental, hash declarado de 64 hexadecimais, responsável e data ISO explícitos; formato conferido, autenticidade do documento declaratório não atestada |
| fields em company | COD_INC_TRIB, IND_APRO_CRED, COD_TIPO_CONT, IND_REG_CUM; membros possíveis conferidos no guia. COD_INC_TRIB não vem do rótulo companies.regime/CRT |
| fields em item | CST_PIS e CST_COFINS; valores textuais conferidos contra a tabela da revisão fixada, sem escolher um CST ou avaliar sua aplicabilidade à operação |
| Campos não informados | Listados em missing_fields; não preenchidos com zero, CST99, regime9 ou valores de outro tributo. Obrigatoriedade condicional não inferida |
| Origem da leitura | id/kind/code/version/active do cadastro e posição da declaração; hash canônico do conteúdo declarado |

Exemplo sintético do namespace em um cadastro de produto (não é payload fiscal):

```json
[{"id":"declaracao-sintetica-produto-1","revision":"1","company_id":1,"scope":"item","direction":"incoming","valid_from":"2026-11","valid_to":"2026-11","reference_id":"contributions-2026-11-review-20261116","source":"Memória sintética do responsável","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","responsible":"Fixture","declared_on":"2026-11-16","fields":{"CST_PIS":"50","CST_COFINS":"70"}}]
```

Valores declarados são preservados e separados dos campos de origem. Códigos numericamente iguais não provam equivalência fiscal. Campos desconhecidos, tipos inválidos, fontes incompletas, duplicidade de id/revision e sobreposição ficam em diagnostics com blocking_export false. Os grupos resumem candidatos elegíveis para revisão, por empresa ou cadastro/direção; sobreposições entre candidatos são sinalizadas. Nenhum grupo atribui campos ao domínio ou resolve automaticamente a declaração da empresa. A avaliação da obrigatoriedade condicional e da adequação da operação permanece false, inclusive quando um código aparece na tabela.

JSON cadastral duplicado ou não finito não recebe interpretação de última chave: a leitura registra metadados ilegíveis/ambíguos com hash e não usa seu conteúdo. Campos genéricos cst, crt, pis, cofins e o regime cadastral não são substitutos do namespace. Dados de outra empresa ficam fora da consulta SQL. Cadastros inativos são observados, sem torná-los candidatos ativos.

A consulta continua exigindo fiscal.documents read/export. Para ler declarações cadastrais, exige também fiscal.masters read, revalidada pelo domínio. Sem essa leitura, a parte documental exporta normalmente e preparation_review retorna not_authorized, records null, sem revelar metadados ou contagem de declarações privadas. Todas as leituras ocorrem no mesmo snapshot transacional, em competências abertas/fechadas/reabertas, sem materializar classificações, alterar contas/lançamentos/saldos ou consultar apurações.

Apenas o estado atual dos metadados é lido. Não foi criado histórico automático das edições cadastrais: reter versões na lista e atestar sua vigência é responsabilidade explícita do fluxo futuro. Vinculação de declarações a itens de documentos, regras condicionais, revisão fiscal, geração e validação no programa oficial continuam pendentes.

## Validação do código local

Execução específica final: 21 testes passaram em 7,427 s, incluindo os 11 da etapa anterior. Build Vite passou e 160 testes Node passaram. AST de seis arquivos, JSON do catálogo, tamanhos/SHA256 dos seis artefatos oficiais e diff-check passaram. O preparo padrão de constraints/cache do CI foi executado em build/, sem alterar requirements ou manifests. O empacotamento existente inclui o diretório app/data completo nos dois specs desktop; instaladores não foram construídos.

A descoberta integral final encontrou **1.148 casos**: **1.112 passaram, zero falhas de asserção, três erros e 33 skips**. Duração do runner: 409,385 s (411,015 s incluindo descoberta). A execução retornou código 1, portanto **a suíte integral não está verde**. Os 21 testes específicos estão incluídos nesses números, não devem ser somados novamente.

Os três erros ocorreram antes das verificações dos testes de socket, em socket.socket(AF_UNIX), com PermissionError: [Errno 1] Operation not permitted, em `test_docker_updates.SocketBoundaryTests`:

- test_invalid_and_oversized_socket_payload_fail_closed;
- test_real_socket_plan_and_job_round_trip;
- test_wrong_peer_uid_and_missing_socket_cannot_execute.

Essas provas usam FakeDocker e um executor temporário; não acionam Docker operacional. Não foram alterados, desabilitados ou simulados os controles de socket para fazê-las passar.

Os skips padrão foram 16 testes PostgreSQL backend e nove de staging PostgreSQL por ausência de DSN descartável, além de oito provas Apple API/TLS que exigem macOS. O driver psycopg 3.3.9 foi instalado em diretório temporário, e as provas de configuração independentes de servidor rodaram. Não foi usado um DSN externo nem simulado PostgreSQL real. Windows/macOS nativos, instaladores e programa oficial não foram executados.

O smoke Chromium foi **tentado e não concluiu**: o browser abortou antes de abrir a página com `process_singleton_posix.cc: socket() failed: Operation not permitted (1)`. O relatório tem ok false e nenhum check visual concluído; não há alegação de UI validada. Não houve mudança de flags, implementação ou testes para contornar a restrição.

Comandos/runner utilizados:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-contributions-testdeps-20261116:/tmp/escritura-sped-testdeps-20261115:tests:scripts:. python3 /tmp/run-contributions-fullsuite-20261116.py
# Runner padrão: unittest.defaultTestLoader.discover('tests') e TextTestRunner(verbosity=2).
# ESCRITURA_DATA_DIR temporário; ESCRITURA_DEMO=0; sem ESCRITURA_POSTGRES_TEST_DSN externo.
# Em frontend/: npm ci --ignore-scripts; npm run build; node --test tests/*.test.js
PYTHONDONTWRITEBYTECODE=1 ESCRITURA_TEST_BROWSER=/usr/bin/chromium PYTHONPATH=/tmp/escritura-contributions-testdeps-20261116:/tmp/escritura-sped-testdeps-20261115:. python3 scripts/smoke_browser.py
```

Logs/resumo completos: /tmp/contributions16-fullsuite.log e /tmp/contributions16-fullsuite.json. Relatório local do navegador: artifacts/browser/report.json (ignorado pelo Git). O runner não filtrou casos: somente os decorators de skip existentes foram respeitados. Não foi alterado comportamento de fluxos existentes para passar testes. Testes internos que geram material criptográfico sintético não usam certificados ou credenciais fiscais reais do usuário.

O código testado é o diff local sobre 87b9139, sem novo commit. O campo source_sha dos relatórios padrão identifica essa base, não uma publicação das alterações. Manifesto dos sete arquivos de código/dados/testes: `cddb5f538ceb41c1fb9e79df7342d7459b85be0a75ac9f7efbb40a636f44de7e`. O manifesto detalhado e logs de testes ficam em /tmp, fora do Git. Artefatos de navegador/build são locais e ignorados.

Próximo passo de validação: repetir as três provas de socket e o smoke em runner que permita sockets Unix, e executar os 25 testes com PostgreSQL descartável e as provas nativas nos respectivos sistemas; até lá a validação integral permanece incompleta. Próximo passo funcional: concluir as regras condicionais e referências históricas faltantes com fontes oficiais, definir edição/versionamento explícito das declarações e sua vinculação controlada aos documentos, mantendo apuração/geração como incrementos separados. Nada nesta frente autoriza transmissão ou encerramento de obrigação.
