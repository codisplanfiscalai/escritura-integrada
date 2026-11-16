# Consolidação opcional na geração a partir da escrituração

## Entrega executável e limite

O endpoint já existente POST /api/companies/{cid}/sped-generator/bookkeeping-block-c
aceita agora consolidate_nfce (booleano, padrão false) e segment_on_gap (booleano,
padrão true). O arquivo individual permanece padrão e é obtido novamente com a
opção desligada, sem alterar documentos, opções de importação ou configuração da
empresa. Esta entrega é API interna; não acrescenta interface nem configuração
persistida por empresa.

Exemplo de corpo (empresa/exercício/módulo ativos, sessão, CSRF e permissões fiscais):

    {"period":"2026-11","profile":"A","activity":"1","purpose":"0","consolidate_nfce":true,"segment_on_gap":true}

Os campos de cabeçalho do exemplo são escolhas explícitas do operador, não valores
presumidos pelo gerador. Também é possível informar header_0000 autorizado como
antes. Ausência de dados/classificações gera avisos e não retira can_export.

Quando aplicada, a opção agrupa somente as NFC-e próprias de saída já abrangidas
pelo projetor, por dia, série canônica e segmento de numeração. Desligar
segment_on_gap permite agrupar lacunas dentro do mesmo dia/série. O agrupamento
reutiliza número/chave da primeira nota conforme a funcionalidade nativa
intencional; a chave continua identificando essa nota, não um novo documento
fiscal correspondente à soma. Não cria lançamento contábil ou consolidação
persistida, nem exige consolidar a importação. Entradas, outros modelos,
canceladas e documentos ainda fora do recorte continuam excluídos com motivos.

O TXT agrupado tem kind=NATIVE_NFCE_OPERATIONAL_PARTIAL_BLOCK_C,
representation=native_operational_nfce_groups e nome iniciado por
consolidacao-operacional-bloco-c. É representação operacional parcial editável/
exportável, não EFD completa nem bloco oficial pronto para importação no PVA.
complete_efd, pva_validated, official_pva_replacement e transmitted são false.
Não contém apuração/saldos ou blocos 0990/9 inventados para aparentar completude.

## Origem, destino e dados desconhecidos

| Componente | Antes | Agora |
| --- | --- | --- |
| bookkeeping.generate_nfce_block_c | Projeta C100/C190 individuais e diagnósticos | Mantém projeção padrão; encaminha a opção explícita ao adaptador |
| native_export._consolidate_native_sped | Port do agrupamento sobre EFD original | Reutilizado também por adaptador interno restrito ao recorte gerado; o caminho público anterior mantém defaults e goldens |
| bookkeeping_native.consolidate_generated_block_c | Ausente | Gera derivado, reconcilia todos os vínculos, hashes e linhas de origem/saída |
| api.bookkeeping_block_c | Não aceitava opção de consolidação | Aceita booleanos explícitos, mantendo contexto e permissões anteriores |
| importação XML/SPED e domínio fiscal | Documentos individuais e originais preservados | Nenhuma mudança; escolha de geração não reescreve a importação |

O caminho novo agrega valores da projeção atual, sem reinterpretar o tratamento
fiscal, criar créditos ou inferir CST. Se qualquer membro tiver um campo monetário
projetado em branco, a soma desse campo permanece em branco; não usa a soma dos
demais como se fosse completa. Alíquota ausente é separada de alíquota explicitamente
zero. Campos vedados da projeção NFC-e e a extensão nativa sem dado continuam
vazios. Campos conhecidos, inclusive zeros explícitos, são somados em Decimal.

Isso é uma adaptação delimitada para a projeção da escrituração. O exportador
público anterior sobre EFD importado conserva inclusive seu tratamento nativo de
vazios; os seis hashes de equivalência com a referência continuam verificados.
Não se declara equivalência byte a byte entre esse exportador completo e o novo
recorte parcial.

**Limite anterior do domínio, observado no teste:** para C190, chave tributária
ausente produz desconhecido, enquanto null explícito em certos campos passa pelo
normalizador fiscal anterior como zero. O adaptador não consegue recuperar uma
ausência já normalizada a montante; preserva o valor da projeção recebida. O serviço
fiscal e o arquivo individual anterior não foram alterados para fazer testes
passarem. Essa distinção exige revisão própria e impede afirmar preservação
universal de null na cadeia inteira. A fixture de ausência usa chave ausente,
conforme o contrato real; a falha inicial com null foi preservada na evidência local.

Caso uma transformação não possa conservar os vínculos (duplicatas, chave
inválida, registro ainda não suportado ou ambiguidade), a resposta mantém o arquivo
individual, consolidated=false e aviso BOOKKEEPING_CONSOLIDATION_NOT_APPLIED.
Empresa/período/permissão/CSRF e tipos de parâmetros continuam sendo verificações
de segurança/integridade; não se convertem em fallback silencioso.

## Rastreabilidade e leitura

- trace conserva um item por documento do recorte exportado, ID, versão, chave, source_hash, data de
  emissão e de escrituração. c100_line aponta agora a linha do grupo na saída;
  source_c100_line aponta a linha do arquivo individual gerado.
- consolidation_trace lista os grupos e todos os membros, incluindo o hash de
  cada linha C100 individual e output_c100_line. Não é prova de assinatura do XML.
- individual_result_sha256 identifica a projeção individual; result_sha256
  identifica exatamente o TXT derivado. Ambos são reproduzíveis.
- summary.exported_documents continua contando documentos de origem;
  output_c100_records conta registros físicos da saída. c190_records é a saída,
  e individual_c190_records conserva a contagem anterior.
- Consultas/exportações funcionam em competência aberta, fechada ou reaberta,
  sem modificar nenhuma tabela, originais, títulos ou partidas. Alterações em
  competência fechada continuam exigindo reabertura; não há nova permissão.

## Fontes oficiais e período conferido em 16/11/2026

[Guia Prático 3.2.4, atualização 30/07/2026](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@download/file):
seção I.9 (p. 6), C100/exceção 9 (p. 64), campos C100 (pp. 65–66).
[NT 2025.001, leiaute 020](https://sped.rfb.gov.br/item/show/7819):
a página oficial identifica vigência de 01/01/2026 a 31/12/2026. O primeiro acesso
direto à página falhou por timeout; a consulta posterior ao índice oficial
recuperou essa identificação. Não se afirma nova leitura integral do anexo NT.

A estrutura oficial não transforma a representação operacional em documento
fiscal individual. O leiaute 020 é a referência da projeção de 2026, não um selo de
conformidade do TXT agrupado. Outros períodos continuam avisados e sem seleção
automática de leiaute; as mudanças previstas para 2027 não foram aplicadas a 2026.

## Matriz honesta de cobertura e lacunas

| Pedido | Situação após este incremento |
| --- | --- |
| SPED do cliente original e consolidação nativa opcional | Mantidos, com goldens anteriores e C140/C141 modelo 55 preservados |
| XML importado individualmente → geração individual ou agrupada | Opção executável acrescentada ao recorte atual, sem mutação da escrituração |
| Consolidação opcional no ato da importação XML, sem gerar SPED | Ainda não implementada; não confundir esta entrega com gravação de lançamentos consolidados |
| Escolha persistida por empresa, interface e arquivo EFD integral | Pendentes; padrão individual/API e Bloco C parcial não completam esses requisitos |
| EFD Fiscal integral e conferência no PVA | Pendentes modelos/blocos/cadastros/itens/ajustes/apurações e validação oficial; nenhuma transmissão |
| RECORD_LIMIT mensal >100.000 registros | Não resolvido; proteção do leitor não foi removida nem ampliada |
| SPED_FIELD_COUNT do C100 nativo de 29 campos de dados | Não resolvido; saída nativa mantém esse formato, com aviso; não truncar o campo nem reimportar grupo como nota real |
| ECD | Snapshot e contratos preparatórios existentes preservados; serializador do livro e validação oficial ainda faltam |
| ECF | Catálogo temporal de referências existente preservado; sem gerador, apuração IRPJ/CSLL ou recuperação oficial implementados |
| EFD-Contribuições | Diagnóstico/declarações/snapshot existentes preservados; sem serializador/apuração/créditos presumidos ou validação PGE |
| Desempenho/armazenamento | Nenhuma medição nova de 90 mil ou ganho em servidor; originais/documentos continuam armazenados |

Todo o objetivo de integração dos recursos e opções originais permanece aberto
até essas lacunas serem concluídas. Este incremento não substitui o manifesto do
projeto nem marca as outras obrigações como implementadas.

## Reprodução e evidência

Com as dependências fixadas do projeto disponíveis, TMPDIR e ESCRITURA_DATA_DIR
devem apontar para diretórios descartáveis num volume de trabalho com espaço.
Nunca usar banco, originais ou backups do usuário.

    python -m scripts.ci.dependencies
    python -m pip install -c build/runtime-constraints.txt -r requirements-test.txt
    PYTHONPATH=.:tests python -m unittest -v test_sped_bookkeeping_consolidation test_sped_bookkeeping test_sped_native_export test_sped_generator
    PYTHONPATH=.:tests python -m unittest discover -s tests -v
    git diff --check

Base de implementação: develop 4610314bc94abbbcecaf271c0e87ca04623525d3 (dev.39),
já contendo PR64, sem alterações de Prosoft, relatórios, recepção DF-e, Atlas,
workflows ou manifests de versão. A publicação PR64 observada no início foi o
run 43966519656 em andamento; não autoriza merge concorrente.

Linha de base em snapshot do HEAD sem alterações: 36 testes passaram em 6,915 s.
As 70 regressões focadas passaram em 15,008 s, incluindo 19 casos novos e seis
goldens nativos. A primeira tentativa sem Cryptodome e a tentativa com constraints
ainda não geradas foram erros do preparo local, preservados; dependências já
declaradas foram instaladas isoladamente, sem mudar requisitos. A primeira
rodada focada teve 69 passes/uma falha da fixture null descrita acima.

Comparação independente antes/depois: 20 cenários (vazio/um/dois/sete documentos,
valores presentes/ausentes/null, avisos e período não verificado) mantiveram bytes
e todos os metadados da resposta individual idênticos ao snapshot da base.

Descoberta integral local: **1.435 testes em 570,170 s: 1.390 passes, zero falhas
de assertiva, quatro erros e 41 saltos; exit 1**. Os quatro erros são os métodos
SocketBoundaryTests do atualizador (incluindo o novo caso de resposta lenta),
todos na criação de AF_UNIX, PermissionError [Errno 1] Operation not permitted.
Os arquivos do executor/testes de socket são idênticos à base. Não se mudaram
permissões, skips, mocks ou executor para encobrir o impedimento. PostgreSQL real
não foi executado sem DSN descartável; os saltos de ambiente estão registrados.
A suíte integral local, portanto, não está verde.

O CI existente deve executar contra o head publicado, incluindo sockets reais
e seu gate PostgreSQL. Não é necessária alteração de workflow; desktop continua
pausado para PRs develop. Frontend/navegador, PVA/PGE, novos benchmarks de 90 mil,
builds e produção não foram executados localmente neste incremento. As evidências
grandes e bancos sintéticos ficam fora do Git.
