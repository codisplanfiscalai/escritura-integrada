# EFD a partir da escrituração: incremento do Bloco C

O objetivo continua sendo gerar a EFD ICMS/IPI integral a partir da escrituração
do Escritura, para conferência no PVA e posterior assinatura/transmissão pelo
responsável. Este incremento implementa uma parte verificável desse caminho:
**arquivo parcial do Bloco C, com NFC-e próprias de saída já escrituradas**.
Não constitui EFD completa, não foi validado em PVA e não transmite obrigações.

## Isolamento e dependência

PR encadeada à PR36, base feat/sped-native-consolidation no commit d9697eb.
A base da PR36 está em f1aac99. Durante o trabalho, a PR34 foi integrada e a
develop avançou para 3a6ab4c; a base encadeada d9697eb permaneceu inalterada.
Não há alterações nas frentes de totais ou armazenamento da PR35. Após integrar a PR36, retargetar
esta PR para develop e repetir os checks. Nenhum arquivo XML real, backup ou
conteúdo da Library foi incluído.

## Regras oficiais verificadas antes de implementar

Consulta em 15/11/2026:

- [Guia Prático 3.2.4, portal SPED](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@download/file):
capítulo I, seção 9 (página 6), importação de blocos; C001 (página 62);
C100 e exceção 9 (páginas 63–68); C190 (páginas 106–107); C990
(páginas 172–173). PDF oficial materializado somente na pasta de análise:
6.557.945 bytes, SHA-256 01e76f177996cb11b1454cbf39f19ad8ce9577876cd8c222ddf3e4aa45b6f164.
- [Nota Técnica 2025.001, leiaute 020](https://sped.rfb.gov.br/item/show/7819):
a página oficial identifica a vigência de 01/01/2026 a 31/12/2026.
[Ato COTEPE 79/25](https://www.confaz.fazenda.gov.br/legislacao/atos/2025/AC079_25)
publica o manual. O download direto do anexo técnico no CONFAZ retornou HTTP 503;
não se afirma confronto integral desse PDF. Os campos deste incremento foram
conferidos no Guia completo acessível.
- A seção 9 permite importar bloco acompanhado do registro 0000 correspondente.
A importação sobrepõe todo o bloco da EFD aberta no PVA. O arquivo gerado contém
0000, C001, C100/C190 e C990; não inventa blocos sem movimento, apuração, créditos,
saldos, obrigações de recolhimento ou inventário.
- C100 usa 29 campos contando REG; C190 usa 12. Cada NFC-e mantém seu C100 e sua
chave. Os campos vedados para NFC-e na exceção 9 ficam vazios. C190 reúne linhas
da mesma nota por CST, CFOP e alíquota; valores desconhecidos ficam em branco,
com aviso, sem se converter em zero.
- Valores de livro e valores declarados são distintos: base/ICMS/IPI seguem as
linhas da escrituração. Para analíticos provenientes de EFD, os C190 normalizados
continuam sendo a fonte. XML não concede crédito automaticamente. Não há
conversão presumida de CSOSN para CST, CFOP de entrada ou regime tributário.
- Não se aplica leiaute 020 automaticamente a outros anos. Fora de 2026, o
cabeçalho gerado deixa COD_VER vazio e avisa que o período não foi verificado.

## Origem e destino do incremento

| Informação | Serviço/dado existente | Destino |
| --- | --- | --- |
| Empresa e competência | company_row, documents.period | 0000 e filtro do snapshot |
| Documento atual | Core._document_values; id/version/status/total_cents | C100 individual e trace |
| Linhas de livro | fiscal_posting_lines | C190, agrupado somente dentro do documento |
| Classificações e valores declarados | analytics/raw_fields; items/taxes | Diagnósticos, campos com origem explícita; sem presumir crédito |
| Emissão e movimentação | issue_date, movement_date, DT_E_S de origem | DT_DOC e DT_E_S separados da competência de escrituração |
| Originais | source_hash e documentos existentes | Hash/ID/versão na trilha; nenhum original alterado |
| Geração anterior | native_export.consolidate_native_sped | Caminho opcional da PR36 mantido e testado |

Arquivo principal: app/sped_generator/bookkeeping.py, generate_nfce_block_c.
Integração: app/sped_generator/api.py, rota bookkeeping-block-c. A extensão de
permissões restringe a nova rota à exportação fiscal; não concede acesso a
originais de importação.

## Contrato e comportamento

POST /api/companies/{cid}/sped-generator/bookkeeping-block-c

Corpo mínimo: period. profile, activity e purpose podem ser informados; ausências
e classificações fiscais incorretas geram avisos. Não são presumidos perfil A,
atividade ou finalidade. Alternativamente, header_0000 recebe a linha do arquivo
já aberto no PVA, com 15 campos. Empresa e competência devem corresponder à
seleção autorizada. O cliente deve conferir a identidade exata desse cabeçalho.

Exige sessão, CSRF, empresa/módulo/exercício ativos, consulta e exportação de
documentos. Revalida permissões no snapshot. Lê a competência completa, sem
paginação, e não altera banco, apuração, fechamento, títulos ou lançamentos.
Competência aberta, fechada ou reaberta permite essa geração somente de leitura.

Retorna bytes em content_base64, encoding ISO-8859-1, CRLF, hash, summary, trace,
skipped e avisos agrupados com os IDs atingidos. complete_efd=false,
pva_validated=false e transmitted=false são explícitos. Advertências fiscais
não bloqueiam a obtenção do arquivo. Dados com delimitadores/controles ou
caracteres não representáveis deixam o campo em branco com diagnóstico, sem
alterar o valor original e sem truncamento silencioso.

São cobertas inicialmente NFC-e próprias de saída, com status booked e origem
normalizada XML ou C100. Pendentes, outros modelos, emissão sem evidência e
situações não ativas ficam identificados em skipped. Não são apagados nem
transformados em documentos regulares. A resposta avisa quando há documentos
não exportados e mantém a advertência de sobreposição do bloco no PVA.

## Limites e próximos passos

Ainda faltam modelos 55 e demais documentos, cadastros/referências completos,
C170, C191/FCP, ajustes C195/C197 e outros registros condicionais, apurações,
inventário, demais blocos e histórico de gerações. A geração de C140/C141 modelo
55 para intercâmbio Prosoft e os recursos nativos seguem no objetivo integral.
Este incremento não remove os leitores/exportadores anteriores.

A escolha persistida por empresa entre SPED fornecido e geração integral,
interface do módulo e integração da consolidação na importação ainda estão
pendentes. O Bloco C parcial não implementa a opção nativa de agrupar várias
notas: essa opção continua no exportador da PR36, com e sem consolidação.
Não há certificado, assinatura ou transmissão nesta rota.

Próxima etapa: ampliar o projetor para os demais modelos e referências, integrar
apurações existentes sem presumir valores e construir o arquivo integral.
Conferir arquivos sintéticos no PVA antes de afirmar cobertura/aptidão de entrega.
A aceitação estrutural no leitor do Escritura não substitui validação no PVA.

## Validação

Testes sintéticos em tests/test_sped_bookkeeping.py cobrem estrutura/campos,
contadores, reimportação com codificação explícita, valores atuais versus origem,
centavos, agrupamento dentro da nota, datas distintas, vazios, chave inválida,
CST/CFOP/indicadores incorretos com avisos, cobertura, autorização, competência
aberta/fechada/reaberta, imutabilidade integral do banco e caminhos de cliente e
nativo. O conjunto inclui mais de 5.000 documentos sem truncamento. Resultados
finais e CI são registrados na PR.

Não executados: PVA, Prosoft, navegador, binários, transmissão ou produção.
Não há inferência de conformidade legal ou economia de armazenamento.

## Medição sintética de volume

Comando: PYTHONPATH=. python3 scripts/benchmark_sped_bookkeeping.py --documents 90000

Uma execução no executor Linux/Python 3.12: 90.000 NFC-e, 90.000 C100, 90.000
C190 e 90.000 referências na trilha; 7,1997 s, 16.076.802 bytes de arquivo e RSS
máximo do processo de 185.096 KiB. Quatro grupos de avisos preservaram os IDs
atingidos. O tempo inclui a criação preguiçosa das fixtures sintéticas, geração e
montagem da trilha; não inclui banco, HTTP/base64, XML, disco ou PVA.
Não é SLA, comparação com produção ou ganho de armazenamento. Neste caminho
individual, não há redução do número de C100. O gerador conserva as identidades.

### Resultado local antes da publicação

- 280 testes passaram em 95,947 s no conjunto fiscal/SPED/domínio, incluindo os
22 testes novos deste incremento e as 258 regressões da base encadeada.
- 47 testes existentes de infraestrutura/CI passaram em 0,715 s.
- Sintaxe AST de cinco arquivos, YAML e git diff --check passaram.
- O filtro de CI inclui somente a base feat/sped-native-consolidation adicional,
com contents: read preservado; não habilita release ou implantação.
- A regressão dos campos vedados da NFC-e inclui valores de origem preenchidos,
para comprovar que a projeção oficial os deixa vazios sem alterar o documento.
- PVA e validação tributária integral permanecem não executados.
