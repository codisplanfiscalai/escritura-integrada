# Arquivos inteiramente fictícios

Estes arquivos são dados sintéticos para os testes de leitura e a demonstração da prévia. Não são documentos autorizados, extratos emitidos por bancos ou amostras homologadas. Chaves, protocolos, CNPJ, CFOP, NCM, valores e alíquotas servem para exercitar campos; não representam enquadramento fiscal válido. Os XMLs são recortes e não devem ser enviados à SEFAZ.

Empresa receptora dos documentos: `12345678000195` (Empresa Fictícia Alfa). Emitente: `87654321000198` (Beta). O CT-e identifica Alfa como remetente **e tomadora**, com uma terceira pessoa como destinatária, para testar que destinatário não é sinônimo de tomador. O valor da prestação, o valor a receber e o valor da carga são diferentes de propósito.

## Contrato dos leitores

`parse_file(nome, bytes, empresa)` produz `documents`, `transactions`, `issues`, `sources`, `format`, `can_confirm` e indicadores de revisão. O parser não grava banco, não cria títulos/partidas e não calcula tributos. A confirmação é responsabilidade da API, que deve bloquear `severity=error`, manter o contexto da empresa, exigir conta financeira para extratos e aplicar idempotência.

Valores monetários são strings de `Decimal`. O hash SHA-256 é da fonte integral; linhas/registro e, em XML, caminho/item identificam a informação extraída. `line=null` em XML significa que o parser não fabricou um número de linha. Os bytes originais precisam ser preservados pelo backend.

### Opções explícitas

Em `company.import_options`, use `encoding` (`utf-8`, `windows-1252`, `iso-8859-1`, `ascii`, `utf-16` com BOM), `date_format` (`YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `DDMMYYYY`, `YYYYMMDD`), `decimal_separator`, `thousands_separator`, `delimiter` e `posting_date` quando pertinente. UTF-8 é a leitura inicial sem perdas; Windows-1252 não é escolhido por tentativa. Ano com dois dígitos não tem século presumido.

Aliases da interface: `DMY` = `DD/MM/YYYY`, `MDY` = `MM/DD/YYYY`, `YMD` = `YYYY-MM-DD`; `encoding="auto"` mantém leitura UTF-8 sem perdas ou BOM/cabeçalho explícito; `delimiter="TAB"` significa tabulação. Movimentos OFX declarados em outra moeda são recusados, pois este contexto financeiro não implementa conversão para BRL. OFC/QIF/CSV sem declaração de moeda exigem conferência com a conta financeira selecionada.

CSV/TXT delimitado usa as quatro colunas canônicas `data;valor;historico;documento`. Um outro cabeçalho requer `bank_columns={"date":"Data do movimento","amount":"Valor","description":"Descrição","reference":"Número"}`. O delimitador só é reconhecido se esse cabeçalho permitir uma identificação única; pode ser informado explicitamente. TXT posicional requer `bank_layout="fixed"` e `bank_columns` com `start` de base zero e `length` para cada um dos quatro campos. Não se presume layout de banco pelo nome do arquivo.

## Escopo e limites

| Leitor | Executado nos testes | Pendente de homologação |
|---|---|---|
| NF-e/NFC-e | Núcleo 4.00, emitente/destinatário, datas, itens, valores declarados, duplicatas e associação de protocolo | XSD completo, assinatura, chave/DV, autorização online, eventos/cancelamentos, versões de NT/RTC e classificação fiscal |
| CT-e | Modelo 57, 4.00; toma3/toma4; total `vTPrest`; empresa emitente/tomadora | CT-e OS, eventos, esquemas completos, casos de substituição/complemento e particularidades de cada operação |
| SPED | EFD ICMS/IPI 020/2026: 0000, 0150, 0200, C100, C170, C190, C140/C141; identificação de registros não processados | Outros leiautes e escriturações, PVA, apuração/ajustes, obrigações, geração/transmissão; importação é parcial declarada |
| OFX | XML e SGML, extrato bancário/cartão, conta/FITID/data/valor/documento/histórico | Variações reais por banco; investimentos, correções e pendentes recusados |
| OFC | Estrutura própria ACCTSTMT/ACCTFROM, tipo numérico, CHKNUM, sinal e dois separadores decimais previstos | Arquivos reais OFC e variações históricas; nenhum EXE V4 foi executado |
| QIF | Seções bancárias, datas explícitas, total, histórico, número, terminador e retenção de rateios | Variações locais, conta múltipla, investimentos e século de datas com dois dígitos |
| CSV/TXT | Leiaute explícito, separador/decimal/data, texto UTF-8 ou encoding configurado | Modelos particulares de bancos, a serem cadastrados e conferidos |
| ZIP | Memória, 20 MiB por arquivo, 80 MiB expandidos, 1.000 membros, proporção 200, dois níveis de contêiner, sem links/caminhos inseguros | RAR e 7z retornam diagnóstico de não suporte; não são anunciados como funcionais |

CFOP de XML de terceiros fica preservado como `source_cfop`/`source_cfops`; o CFOP da escrituração da empresa ativa permanece sem classificação. Em SPED, o CFOP é do declarante. `posting_date_proposed` identifica a data sugerida a partir da emissão quando não foi informada uma data de escrituração. `C190` continua analítico e não vira um item fictício; `C141` não vira baixa financeira.

## Documentação de origem dos campos

- [Guia Prático EFD ICMS/IPI 3.2.4](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@display-file/file), registros identificados na tabela acima.
- [NT 2025.001 — leiaute 020, vigência 2026](https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais/06___anexo_2.pdf/@@download/file/06___ANEXO_2.pdf).
- [MOC NF-e 7.0, Anexo I](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=J+I+v4eN00E%3D), campos do núcleo de documento, itens e total.
- [MOC CT-e 4.00, Anexo I](https://www.cte.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=6aFNuknaWsc%3D), especialmente grupos toma3/toma4 e vPrest.
- [OFX Banking 2.3 — Financial Data Exchange](https://financialdataexchange.org/common/Uploaded%20files/OFX%20files/OFX%20Banking%20Specification%20v2.3.pdf), extratos e STMTTRN.
- [Documento Intuit sobre QIF preservado pelo W3C](https://www.w3.org/2000/10/swap/pim/qif-doc/QIF-doc.htm), campos e seções originais.
- [Especificação Microsoft OFC 1.0.6 preservada pelo MnyBank](https://mnybank.sourceforge.net/Specs_Ofc.html), cópia histórica do documento original, sujeita a homologação real.
