# EFD-Contribuições: composição local dev.26/dev.27 e descoberta preparatória

## Base e preservação

Composição local sobre `12103b555d295489fe6a06de836c00b257562ce2` (`0.9.0-dev.26`),
conferida com `develop` no início da tarefa em 16/11/2026. O checkout anterior
`escritura-contributions-local-20261116`, base `87b9139` (dev.20), permanece intacto:
seus nove arquivos modificados/não rastreados foram inventariados por SHA256 antes
da composição e conferidos novamente ao final. Não houve rebase, reset ou edição
nesse worktree. Os artefatos de preservação/testes ficam fora do Git.

A base inicial dev.26 já contém PR43 (catálogo SPED), PR44 (interface Prosoft) e PR57
(índice de identidade para cancelamentos NFC-e). Nessa etapa, PR51 ainda não integrava
a base. Depois, a recomposição dev.27 recebeu PR51 já mesclada por seu responsável,
como descrito abaixo. Nenhuma dessas entregas é reivindicada como nova funcionalidade
de Contribuições. Workflows, versões, dependências e código Prosoft são preservados
da respectiva base; não houve novo merge remoto da PR51 nesta tarefa.

## Avanço delimitado

O diagnóstico documental e os contratos declarativos anteriores foram transportados
sem conflito. Continuam sem escolher CST/regime, aplicar classificação, reconhecer
crédito, apurar tributos, gerar EFD ou transmitir obrigação.

A lacuna de descoberta foi fechada no catálogo autenticado `/api/sped/obligations`:

- `preparations` é separado de `exports` de arquivo da obrigação;
- indica os snapshots JSON preparatórios conhecidos de ECD e Contribuições somente
  quando o método GET e o caminho exatos estão registrados na aplicação em execução;
- mantém `implementation: not_implemented`, `complete_file_generator: false`,
  `generates_obligation_file: false` e `validated_in_official_program: false`;
- declara necessidade de contexto/empresa autorizados e ausência de mutação;
- não concede permissões nem transforma catálogo global em exportação de dados.

Esse campo não é inventário de todas as rotinas preparatórias. O catálogo temporal
ECF já existente não foi transformado em serializador ou snapshot contábil. As datas
e o conteúdo das referências fiscais anteriores não foram reinterpretados. Os seis
artefatos oficiais já preservados foram conferidos por tamanho/hash contra o catálogo;
não houve novo download ou homologação jurídica/PGE/PVA nesta composição.

Os quatro testes novos verificam reconhecimento exato da rota, resposta não mutável,
sem falsa promessa de gerador, catálogo sem dados de empresa, permissões e preservação
integral do banco/índice da PR57 durante consultas. As provas anteriores de isolamento,
origem, períodos, metadados privados, null versus zero e declarações não aplicadas
continuam executadas separadamente.

## Evidência desta composição

- 21 testes específicos anteriores: passaram em 8,065 s.
- 34 testes de Contribuições/composição/catálogo: passaram em 11,013 s; incluem os quatro
  novos casos. Não somar os 21 como casos adicionais desta execução.
- Regressão focada ampla: 318 testes passaram em 139,316 s, sem falhas, erros ou skips,
  incluindo SPED/ECD/ECF, Prosoft, índice/contratos NFC-e, contabilização e reprocessamento.
  Não é descoberta integral da suíte nem homologação externa.
- Frontend da base dev.26: 177 testes Node passaram; build aprovado, com aviso existente
  de chunk maior que 500 kB. Nenhuma interface de preparação nova foi acrescentada.
- AST de 230 arquivos Python, JSON e integridade dos seis artefatos preservados aprovados.
- Sem alterações nos manifests de versão ou nos workflows; nenhuma dependência foi mudada.

A suíte integral histórica de dev.20 com três erros de socket e 33 skips permanece
registrada no documento anterior. Uma regressão focada verde não a transforma em
aprovação integral. Nesta composição não foram executados programa oficial, PostgreSQL
real, Docker operacional, binários nativos, importação Prosoft ou navegador visual.

## Bloqueios e próximo responsável

Não existe arquivo EFD-Contribuições pronto para transmissão. Faltam regras condicionais,
edição/versionamento explícitos das declarações, vínculo controlado aos documentos,
matrizes por bloco, regimes, créditos/retidos/apuração, cadeia histórica e validação
no programa oficial. Consulta JSON e presença no catálogo não resolvem esses pontos.

A documentação de escopo anterior permanece em
[EFD_CONTRIBUICOES_DIAGNOSTICO.md](EFD_CONTRIBUICOES_DIAGNOSTICO.md) e
[EFD_CONTRIBUICOES_DECLARACOES.md](EFD_CONTRIBUICOES_DECLARACOES.md). Qualquer integração
posterior exige composição/CI no head corrente, revisão e autorização própria de
publicação. Não houve push, PR, merge, release, implantação, alteração de DIX real,
transmissão ou implantação de Atlas nesta tarefa.

## Recomposição posterior sobre dev.27

Durante a validação, a PR51 foi mesclada por seu responsável e `develop` avançou para
`ee6153f956628f12caa6daaed03f88b8ee2b2237` (`0.9.0-dev.27`). O checkpoint local dev.26
foi preservado em `084564bfe5f1982d263a83ee2178c60fa06c73d8` e a recomposição local recebeu
esse novo head, sem conflitos, rebase ou force push. Isso não executou novo merge no GitHub.

A leitura usou explicitamente `refs/heads/develop`: existe também uma tag móvel `develop`,
que não deve ser confundida com a branch. O SHA foi confrontado com a consulta do conector
GitHub antes de compor. Os modelos Prosoft e seus testes de contrato agora vêm da PR51 já
integrada; não foram modificados nesta frente. Workflows e cinco manifests de versão são
idênticos à nova base. Os arquivos de Contribuições continuam os mesmos da composição
anterior, além desta atualização de evidência.

A revalidação dev.27 passou: **327 testes backend em 143,375 s**, sem falhas, erros
ou skips, incluindo os nove contratos independentes Prosoft agora na base. A revisão
independente repetiu os 34 testes específicos/catálogo em 11,277 s. **177 testes Node
e build** passaram novamente nesta composição. AST de 300 arquivos Python e diff-check
aprovados. Os resultados dev.26 acima não são apresentados como execução do novo head.
São regressões focadas, não suíte integral, PVA/PGE, PostgreSQL ou navegador. Nenhuma release, imagem,
instalação ou base DIX foi alterada por esta recomposição local.

## Publicação posterior e compatibilidade com dev.28

Depois da autorização de publicação, a mesma árvore dev.27 foi aberta como
PR59 em rascunho, head `63feb3e011fa3f02fe38d9c0d639a99d321f835a`. O CI
`43855334675` desse head concluiu com sucesso. Isso não torna a preparação um
gerador EFD e não comprova por si o resultado de um head posterior.

A sincronização seguinte recebe `develop`
`e25da58c9c919415968bdecc4caa9b12450367ca` (`0.9.0-dev.28`), que já inclui a
PR56 de cadastros compartilhados. Os serviços de Contribuições não foram
reescritos: as declarações continuam em cadastros locais de estabelecimento,
produto ou serviço, com `company_id` exato e `fiscal.masters/read`. Terceiros e
contadores globais não promovem esse namespace nem concedem acesso à escrituração.

Uma regressão adicional cria evidência sintética privada em duas empresas e um
terceiro global. Confere que o snapshot autorizado contém somente as declarações
da empresa consultada; leitura global com permissão de exportar documentos não
libera as declarações sem `fiscal.masters/read`, nem o acesso à outra empresa.
O hash integral do banco permanece igual durante as consultas. Os 18 testes de
composição/cadastros passaram e foram repetidos por revisão independente; 180
testes frontend e build passaram nesta composição, com o aviso de chunk existente.
A regressão backend focada ampla passou: 354 testes em 153,087 s, sem falhas,
erros ou skips, incluindo terceiros/cadastros compartilhados além das frentes
anteriores. AST de 304 arquivos Python, JSON e diff-check aprovados. Continua
sendo regressão focada local, não homologação fiscal, PostgreSQL ou navegador.

A sincronização deve preservar o head remoto anterior como ancestral, sem rebase
ou force push, e disparar CI próprio. Não autoriza merge da PR, release ou
implantação; a publicação concorrente de dev.28 não é alterada. Nenhum dado
real, transmissão fiscal, PGE/PVA ou implantação do Atlas faz parte desta etapa.
