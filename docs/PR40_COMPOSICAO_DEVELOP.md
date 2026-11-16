# PR40: composição com develop dev.14

A branch `feat/prosoft-fiscal-accounting-increment`, em
`5b528cdd06e9b267187f905695c7ec75ebae7bf9`, foi composta com o develop
`34e816c798daf4f2cb30aaac188065599f912cce` (dev.14). A atualização preserva os
dois históricos por um commit com dois pais; não é integração da PR no develop.

## Conflito e resolução

O único conflito de conteúdo foi em `app/business.py`, na lista de bases de
`BusinessCore`. A PR40 adicionava `ProsoftFiscalMixin`; o develop adicionava
`FiscalSalesAccountingMixin`. A composição mantém ambos, nessa ordem, com os
imports correspondentes. Os métodos dos dois mixins não se sobrepõem. A
implementação de estorno de saídas e seus caminhos de `super()` do develop
permanecem disponíveis.

README e permissões foram compostos automaticamente e conferidos: exportação
fiscal Prosoft mantém sua permissão própria e contabilização de saídas/SPED
mantêm as regras do develop. Docker, desempenho, versões e pacotes recebidos do
develop não foram editados nesta resolução. Não há migração de schema.

## Provas sintéticas de composição

`tests/test_fiscal_sales_composition.py` mantém os seis cenários existentes e
acrescenta três:

1. Três NFC-e importadas e escrituradas continuam com três registros fiscais de
   2611 posições após gerar um lançamento diário. O TXT fiscal mantém o hash;
   a mudança do snapshot pelo vínculo contábil invalida a prévia anterior. A
   exportação do snapshot atualizado preserva os registros econômicos e o Bloco C.
   Um lançamento sintético representável, selecionado explicitamente, produz
   CTA/LC1/LC2 de 208/448/342 posições, reconcilia três centavos, usa plano 052 e
   repete o mesmo lote na confirmação idempotente.
2. O estorno parcial de uma contribuição diária mantém original e compensação,
   ambas balanceadas, e apenas a nota não escriturada fica fora da exportação
   fiscal. Prosoft e Bloco C conciliam o total fiscal de 200,00. Consultas e
   prévias não modificam banco, fontes ou vínculos.
3. Exportações fiscal e contábil representáveis permanecem disponíveis na
   competência fechada; a geração contábil de outro documento continua recusada.
   Exportar não reabre competência nem altera registros econômicos.

As fixtures usam XMLs fictícios, CNPJ numérico de teste, originais BLOB e bancos
SQLite temporários. Nenhum arquivo privado é necessário para os testes.

## Limite encontrado e decisão posterior

A composição inicial identificou o excesso da referência da rotina diária em
relação às dez posições CTBLCTOS e manteve a rejeição até haver decisão. Em
16/11/2026, o usuário autorizou referência curta rastreável apenas na saída.
O encoder agora gera a forma determinística, conserva a original na aplicação
e salva ambos os valores no manifesto imutável. Os testes de composição exigem
exportar o lançamento diário e sua compensação sem renomear as fontes. O
[contrato do exportador](EXPORTACAO_PROSOFT_INCREMENTO.md) descreve posições,
rastreio, colisões e limites. A decisão também autoriza incluir as canceladas
já identificadas/escrituradas, com o indicador próprio do layout.

As demais lacunas de [exportação Prosoft](EXPORTACAO_PROSOFT_INCREMENTO.md)
permanecem: perfil fiscal parcial, CTA opcional, sem TRC/SLD, sem EFD oficial ou
transmissão. Não houve teste na instalação Prosoft, homologação, alteração de
produção, publicação de dados reais, release ou implantação. A PR44 não foi
editada nem sua branch atualizada nesta etapa.

## Validação

- Os nove testes de composição passaram, incluindo os três novos cenários.
- A rodada integral final coletou **997 testes**: **969 aprovados, 28 não
  executados** por exigirem `ESCRITURA_POSTGRES_TEST_DSN` de banco descartável;
  zero falhas/erros, 363,625 s incluindo descoberta. Não foram acrescentados skips.
- **141 testes de interface**, build Vite, sintaxe Python e diff-check passaram.
  Permanece o aviso preexistente de chunk acima de 500 kB; não há lint configurado.
- A primeira rodada integral detectou os leitores 7z/RAR ausentes neste executor.
  `py7zr==1.1.4` e `rarfile==4.5`, com as constraints existentes, foram instalados
  somente em diretório temporário. Os 16 testes de compactados e depois a suíte
  integral passaram; requisitos/locks ficaram intactos.
- O CI remoto do novo head é registrado na descrição da PR. Os testes locais não
  equivalem a PostgreSQL operacional, build/smoke nativos, PVA ou importação Prosoft.

```bash
PYTHONPATH=tests:. ESCRITURA_DEMO=0 python -m unittest test_fiscal_sales_composition -v
PYTHONPATH=tests:. ESCRITURA_DEMO=0 python -m unittest discover -s tests -v
(cd frontend && npm ci && npm run build && node --test tests/*.test.js)
python -m compileall -q app scripts tests
git diff --check
```
