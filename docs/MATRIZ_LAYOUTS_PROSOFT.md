# Matriz dos layouts Prosoft

Conferência em 16/11/2026. SPED é ferramenta interna separada e não preenche as
lacunas dos formatos próprios Prosoft. Nenhum perfil foi homologado por
importação real no destino. Não há escrita na base Prosoft nem transmissão.
Esta matriz contém contratos de código e inventário de categorias; não reproduz
pacotes, planilhas, nomes de clientes, dados ou identificadores privados.

## Situação de publicação

A = API nativa integrada pela PR40. B = operação/mapeamentos e seleções
integradas pelas PR44/62 e espécies corrigidas pela PR51. C = perfil TRC PJ
mínimo implementado nesta branch, sujeito à revisão e CI da PR; P = formato não
implementado. Base conferida: develop dev.39
`4610314bc94abbbcecaf271c0e87ca04623525d3`. A consulta JSON de saldos observados
da PR65 é preparatória: não gera SLD nem comprova abertura/completude.
Publicação/CI de um head não são homologação Prosoft nem aprovação de outro head.

## Fiscal TXT: vinte modelos conferidos

Arquivos produzidos: `ENTRADAS.TXT` / `SAIDAS.TXT`, nomes de intercâmbio escolhidos
pelo aplicativo, dentro de `PROSOFT_FISCAL_<empresa>_<AAAAMM>.zip` com
`manifest.json`. ZIP/JSON não são layouts Prosoft e não se alega importação direta
do ZIP. Para modelos pendentes não são inventados nomes de arquivo. As páginas
referem-se ao layout fiscal fornecido, conferido separadamente do repositório.

| Arquivo/modelo | Páginas | Código/teste/publicação | Falta concreta |
|---|---|---|---|
| `ENTRADAS.TXT`, notas 55/65, 2340 posições | 1–7; cancelamento 3 | A parcial; B entradas/ambas | Restantes campos fiscais, itens/cadastros/faturas e aceite no destino |
| `SAIDAS.TXT`, notas 55/65, 2611 posições | 11–18; cancelamento 13 | A parcial; B saídas/ambas | Restantes campos fiscais e aceite no destino; não consolida NFC-e |
| Mapa Resumo ECF | 22–25 | P | Encoder, origem ECF/contadores/reduções e testes |
| Itens de notas de entrada | 27–34 | P | Arquivo de itens e vínculo cabeçalho/desdobramento |
| Itens de notas de saída | 38–45 | P | Arquivo de itens e vínculo cabeçalho/desdobramento |
| Inventário TXT | 48 | P | Estoque/data, situação/terceiros, valores e impostos |
| RCPE | 49 | P | Movimentos de produção/estoque com origem explícita |
| Produtos | 50–53 | P | Cadastro, códigos do destino e campos completos |
| Faturas | 56–57 | P | Vínculo documental, parcelas, CLI e reconciliação |
| Itens de cupom fiscal | 58–59 | P | Mestre/detalhe, ECF/cupom/produto e totais |
| Serviços prestados SP | 60–65 | P | Livro/modelo, tomador, município/ISS/retenções |
| Serviços tomados SP | 73–78 | P | Livro/modelo, prestador, ISS/retenções |
| Serviços prestados BA | 88–91 | P | Modelo e campos municipais |
| Serviços prestados, outros municípios v1 | 98–101 | P | Versão/modelo de destino e campos municipais |
| Serviços prestados RJ | 109–111 | P | Modelo e campos municipais |
| Valores avulsos para integração | 117 | P | Mapa/máquina, CLI, tipo/valor e origem |
| Itens de faturas | 118 | P | Fatura/vencimento/terceiro e campos próprios |
| Meios de pagamentos | 119 | P | Tabela do destino, valor e vínculo com a nota |
| Serviços: redução BC IBS/CBS | 120 | P | Modelo de serviços e bases/reduções comprovadas |
| Chave de acesso complementar | 121 | P | Tipo/origem e vínculo; distinta da chave NF-e do cabeçalho |

A cobre escrituração separada da emissão, identidade moderna, espécie/conta por
mapeamento, CFOP/desdobramentos e valores de livro já informados, chave,
contraparte representável, fontes, totais, prévia/hash, lote/replay/permissões.
Campos não implementados ficam em branco com avisos/limites; não são gerados
ST/FCP/DIFAL, PIS/COFINS, IBS/CBS e ajustes. Não se infere crédito/regra por
CFOP/regime. A semântica de branco no importador exige ensaio no destino.

Canceladas cobertas são somente as já identificadas pelo livro validado e
escrituradas, com total zero. `Nota Cancelada`: entrada 809×1 / saída 930×1,
`1` cancelada / `0` regular. Identidade, datas, fontes e contagem são preservadas.
Não se cria evidência eletrônica nem se inventa código de `Situação Docto` da
tabela do destino. Pendentes/não escrituradas continuam fora.

## Contábil CTBLCTOS: cinco registros conferidos

Arquivo `CTBLCTOS<empresa4>_<AAAAMM>.TXT`, ASCII/CRLF. Plano 050 padrão de
conferência, outro plano por escolha explícita; o arquivo não contém campo de
plano. Conferir a mesma empresa/plano e a rotina na instalação de destino.
Páginas abaixo referem-se ao layout contábil fornecido.

| Registro | Páginas | Código/teste/publicação | Falta concreta |
|---|---|---|---|
| CTA, 208 posições | 2 | A opcional; B incluir/excluir sem apagar configuração | Só contas movimentadas declaradas ausentes; sem consulta ao cadastro remoto |
| TRC PJ mínimo, 646 posições | 3–4 | C opcional, integrado aos perfis de lançamentos | CPF/PF/livre e demais campos pendentes; ambiguidades pessoais não resolvidas; aceite no destino |
| LC1, 448 posições | 4–5 | Preexistente develop/main; A amplia; B opera UI | Conciliação não derivada; aceite real pendente |
| LC2, 342 posições | 5 | Preexistente develop/main; A preserva; B perfil LC1/LC2 | Até 200 partidas; aceite real pendente |
| SLD | 6 | P | Exercício/saldo inicial/movimentos, reaplicação sem dupla contagem, encoder e testes |

LC1 recebe referência curta rastreável somente em 21×10 quando a original excede
dez caracteres. Original da aplicação preservada; mapa completo no manifesto
imutável, consultável sob permissão de exportação. Algoritmo e colisões no
[contrato](EXPORTACAO_PROSOFT_INCREMENTO.md). Não é idempotência global do destino.

Plano completo é outra rotina, distinta de CTA: `CTBPLANO<plano>.TXT`, com P de
103 posições e C de 204; `PLANO-<plano>.TXT`, linhas de 204, é o formato de
exportação de plano. Já existentes em develop/main, com codecs e roundtrip
sintéticos em `tests/test_account_plan_codec.py`. Não são registros CTBLCTOS.
As perdas e ambiguidades estão no [contrato de plano](PLANO_CONTAS_INTERCAMBIO.md).
Sua existência não comprova homologação da instalação de destino.

## Modelos Excel conferidos

| Categoria | Estrutura examinada | Exportação Prosoft |
|---|---|---|
| Plano de saúde R4010 | 13 cabeçalhos | P; não implica emissão de evento oficial |
| Contas a pagar/receber | 20 cabeçalhos não vazios | P; títulos e Excel genérico não emitem esse modelo |
| Inventário | 17 cabeçalhos | P; encoder do modelo ainda ausente |

Somente a estrutura foi necessária. Exemplos operacionais e acompanhamento de
homologação não são fixtures nem prova de aceite desta versão.

## Testes e limites

- `app/prosoft_fiscal.py` / `tests/test_prosoft_increment.py`: posições, datas,
  centavos, desdobramentos, campos ausentes, fontes, seleção e lotes fiscais.
- `app/prosoft.py`, `tests/test_business.py`, `tests/test_prosoft_increment.py`,
  `tests/test_journal_participants.py`: CTA/LC1/LC2, terceiros/centros, histórico,
  plano escolhido, ASCII e identidade de lotes históricos.
- `tests/test_prosoft_cancel_references.py`: cancelamento/zero/identidade,
  posições, determinismo, colisões simuladas, permissões, manifesto persistido,
  replay, rollback e originais preservados.
- `tests/test_fiscal_sales_composition.py`: contabilização diária, compensação,
  competência fechada, referência curta e independência do Bloco C.
- PR44: testes de configurações, frontend e `scripts/browser_prosoft_export.py`
  cobrem seleção, persistência/contexto, permissões, downloads e posições. A
  composição com esta base precisa repetir UI/CI.

Faltam para homologar: acesso confirmado à instalação/versão/rotina Prosoft,
importação sintética controlada, reconciliação de campos/totais, semântica de
brancos, cadastro/plano e reimportação/rollback no destino. Não se presume aceite
por CI, prévia, arquivo gerado ou planilha de acompanhamento. Não é necessário
reenviar os layouts já localizados.

Validação histórica do incremento inicial: 72 regressões diretamente afetadas aprovadas
em 23,910 s; 160 testes frontend e build aprovados; sintaxe e diff-check aprovados.
A suíte integral coletou 1.094 testes: 1.063 aprovados, 28 PostgreSQL sem DSN
local e três erros de criação de socket Unix no executor (`EPERM`). Uma chamada
mínima sem importar o app reproduziu a restrição. Os arquivos do atualizador
Docker são idênticos ao develop; nenhum teste foi removido, contornado ou
acrescentado como skip. O CI remoto deve executar os testes completos, inclusive
sockets Unix e PostgreSQL real, antes da integração da PR.

O [contrato TRC PJ mínimo](PROSOFT_TRC_PJ.md) descreve posições, escolhas,
limites, rastreabilidade e provas deste novo perfil. Não é suporte integral TRC.
