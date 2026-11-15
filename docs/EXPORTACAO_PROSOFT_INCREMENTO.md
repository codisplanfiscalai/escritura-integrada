# Exportação Prosoft fiscal e contábil — incremento parcial

A API prepara arquivos para intercâmbio e conferência no Prosoft, sem escrever na instalação de destino. O fiscal passa a gerar notas de entrada/saída; o contábil existente ganha CTA opcional. **Não há homologação no Prosoft, geração de EFD oficial, transmissão, encerramento, merge ou implantação nesta entrega.** A interface existente não foi ampliada: as capacidades novas são utilizáveis pela API autenticada, com sessão, contexto de empresa/exercício e CSRF do aplicativo.

## Fontes técnicas e confronto

- `Prosoft.zip/LAYOUT_CTBLCTOS.PDF`: especificação ASCII na página 1, CTA de 208 posições na página 2, TRC nas páginas 3–4, LC1/LC2 nas páginas 4–5 e SLD na página 6.
- `Prosoft.zip/layoutimportdos_29102026.pdf`, versão fornecida de 29/10/2026: notas de entrada nas páginas 1–7, notas de saída nas páginas 11–17 e observações de substituição dos campos legados na página 18. Os últimos campos terminam em 2340 e 2611, respectivamente.
- O pacote de exemplo privado foi materializado e lido separadamente da cópia Git. Seus metadados de layout confirmam esses comprimentos; as notas de cabeçalho de 2340/2611 posições foram confrontadas por estatísticas de formato, sem copiar documentos. Todas as notas desses dois comprimentos usam espécie/série/número nos campos modernos e deixam os correspondentes legados em branco, comportamento mantido pelo perfil. Arquivos de itens/faturas do exemplo têm perfis distintos e não são tratados como notas. Nenhum exemplo contábil LC1/LC2/CTA/TRC/SLD foi encontrado entre os arquivos TXT/preview inspecionados; a referência normativa deste incremento contábil é o PDF fornecido. A presença dos arquivos não comprova importação aceita no destino.

Somente código, documentação e testes construídos com dados fictícios entram na PR. Pacotes privados, planilhas de homologação, arquivos fiscais reais e identificadores do escritório não são fixtures nem artefatos publicados. A planilha de homologação está disponível, mas não é evidência de execução desta versão no destino.

## Cobertura e lacunas

| Fluxo/registro | Implementado neste incremento | Limite concreto |
|---|---|---|
| Notas fiscais de entrada | ASCII/CRLF, 2340 posições, modelos 55/65 já escriturados | Perfil parcial de cabeçalho e desdobramentos; conferir importador e versão instalados |
| Notas fiscais de saída | ASCII/CRLF, 2611 posições, modelos 55/65 já escriturados | Uma nota por documento; sem consolidação diária ou transformação de NFC-e |
| Origem e reconciliação fiscal | Competência pela escrituração, emissão separada, chave, fontes conhecidas, hash de snapshot e total por linha | Não reconstitui campos ausentes nem substitui o XML/SPED original |
| Tratamento fiscal | Valores já produzidos por `fiscal_posting_lines`, incluindo C190 existente | CFOP/regime não autorizam crédito ou classificam a operação automaticamente |
| Plano e contas | Plano de conferência padrão `0050` (050), escolhível; conta fiscal por CFOP e empresa da requisição | Plano não é um campo desses arquivos; selecionar o mesmo plano no destino. Mapeamentos enviados por chamada, sem novo cadastro persistente |
| CTA | Conta movimentada declarada ausente no destino; 208 posições antes de LC1/LC2 | Inclusão opcional explícita; não exporta o plano inteiro nem verifica cadastro remoto |
| LC1/LC2 | Fluxo anterior preservado, 448/342 posições, hash, lote e download | Não cria lançamentos novos; não muda contabilização diária da outra frente |
| TRC | Não gerado; referência de terceiro do LC1/LC2 continua disponível | Resolver divergência CPF na convenção geral versus tabela TRC e sobreposição de posições 501–508 no PDF antes de perfil cadastral |
| SLD | Não gerado | Definir exercício, saldo inicial versus movimentos mensais, terceiros/centros e política de reaplicação no destino; impedir somar duas vezes saldos e lançamentos |
| Demais fiscal | Não gerados | Itens, faturas, meios de pagamento, cadastros, ST/FCP/DIFAL, PIS/COFINS, IBS/CBS, ajustes, serviços/transporte e canceladas |
| Prosoft/PVA | Não executados | Sem acesso confirmado à instalação Windows/RDP; nenhum aceite de importação ou validação PVA desta versão |

## API fiscal

As três rotas abaixo usam a permissão própria `fiscal.prosoft:export`; conceder também `read` permite escolher o módulo fiscal na sessão. As permissões por empresa e o mecanismo normal de CSRF continuam aplicáveis.

```text
POST /api/companies/{cid}/prosoft-fiscal/preview
POST /api/companies/{cid}/prosoft-fiscal/confirm
GET  /api/companies/{cid}/prosoft-fiscal/exports/{id}/download
```

Exemplo exclusivamente sintético de payload de prévia:

```json
{
  "period": "2026-11",
  "company_code": "99",
  "plan_code": "050",
  "species": {
    "55": {"code": "NFE", "confirmed": true},
    "65": {"code": "NFCE", "confirmed": true}
  },
  "cfop_accounts": {
    "1102": {"code": "123", "confirmed": true},
    "5102": {"code": "456", "confirmed": true}
  }
}
```

`species` é o código cadastrado na instalação de destino, não um valor escolhido automaticamente a partir do modelo. Os códigos acima são exemplos, sem promessa de equivalência com uma tabela instalada. `document_ids`, opcional, seleciona documentos existentes da mesma empresa e competência; omitir seleciona todos os documentos do mês. A seleção usa `posting_date`, preservando `issue_date` mesmo em outro mês. Empresa e plano do destino são normalizados para quatro dígitos e integram a identidade do lote.

A prévia retorna `preview_hash`, `sha256`, `filename`, `manifest` e amostras. O manifesto identifica notas não exportadas (`skipped` com motivo e total), avisos por documento/linha, conversões textuais, totais de cada direção e trilha de cada registro. A confirmação repete o payload e acrescenta:

```json
{"preview_hash": "HASH_DA_PREVIA", "destination_reviewed": true}
```

Se houve conversão ASCII, acrescentar `allow_ascii: true` após conferir `text_changes`. Aceitar a conversão não muda o hash nem os bytes da prévia fiscal. `needs_ascii_review` do manifesto registra que existem mudanças textuais, mesmo após o aceite, para permanecer determinístico. Campos tributários ou conta fiscal ausentes produzem avisos e **não impedem** gerar um lote que contenha alguma nota coberta. Sem espécie mapeada, a nota fica em `skipped`; sem notas cobertas, a prévia continua explicativa e não se grava lote vazio.

O download contém `ENTRADAS.TXT` e/ou `SAIDAS.TXT` e `manifest.json`. O ZIP usa nomes fixos, ordem e data interna determinísticas. Os nomes são de intercâmbio do aplicativo: a rotina de importação do destino deve selecionar o TXT correspondente; não se afirma que o ZIP seja importável diretamente.

### Origem dos campos fiscais

Posições abaixo são contadas a partir de 1. Cada linha vem da mesma função analítica usada pelos livros existentes; valores de cabeçalho não são repetidos em todos os desdobramentos.

| Campo | Origem | Entrada: posição × tamanho | Saída: posição × tamanho |
|---|---|---|---|
| Escrituração / emissão | `posting_date` / `issue_date`, DDMMAA | 19×6 / 25×6 | 20×6 / 728×6 |
| Número moderno | `number`, zero à esquerda, sem corte | 869×10 | 989×10 e 999×10, mesmo número inicial/final |
| Espécie Windows / série moderna | Mapeamento explícito / `series` atual | 858×5 / 864×3 | 978×5 / 984×3 |
| Desdobramento | Ordem estável das linhas: 1–9, A–Z | 43×1 | 19×1 |
| Acesso fiscal no destino | `cfop_accounts[cfop]`, quando confirmado | 44×5 | 26×5 |
| CFOP atual | CFOP da linha analítica | 624×4 | 734×4 |
| Valor contábil | `document_total`, parcela da linha | 211×14 | 34×14 |
| Base / ICMS do livro | `book_base` / `book_icms`, quando informados | 66×14 / 80×14 | 62×14 / 76×14 |
| Outras / IPI do livro | `book_other` / `book_ipi`, quando informados | 108×14 / 155×14 | 104×14 / 132×14 |
| Alíquota | `rate`, somente se representável em duas casas | 136×5 | 188×5 |
| Chave eletrônica | `key`, quando existente | 973×44 | 1377×44 |
| CNPJ / UF / IE da contraparte | Documento atual; emitente na entrada e destinatário na saída | 5×14 / 517×2 / 499×18 | 254×14 / 273×2 / 1037×18 |

Os campos antigos de série/número/espécie ficam em branco neste perfil Windows. Os demais campos sem origem implementada também ficam em branco. Não usar `document_total` como valor de mercadorias: os componentes podem incluir frete, descontos, IPI ou outros valores. A ausência de crédito não equivale a zero. CPF/CNPJ alfanumérico não cabe no campo de CNPJ numérico deste perfil: deixa-se em branco com aviso. Alíquota com quatro decimais não é arredondada para caber; este incremento ainda não preenche o campo especial previsto para certas alíquotas. O importador pode interpretar brancos como zero; essa semântica requer ensaio no destino antes do uso operacional.

Totais de valor contábil precisam reconciliar por nota. Totais fiscais informados e quantidade de linhas informadas por campo permitem distinguir soma conhecida de ausência. Limites técnicos: DDMMAA entre 2000 e 2099; número de até dez dígitos; série de três posições; chave de 44 dígitos; até 35 desdobramentos; valores não negativos dentro da largura do campo; ASCII sem controles. Dados que excedem o perfil são recusados sem truncamento ou descarte silencioso. Não são bloqueios de aplicabilidade fiscal.

## CTA contábil opcional

As rotas contábeis existentes `/prosoft/preview`, `/prosoft/confirm` e `/exports/{id}/download` continuam sob `accounting.prosoft`. `plan_code` é opcional e tem padrão `050`; outro plano é aceito, validado e incluído no hash. Não muda o plano ativo da empresa nem o cadastro do destino. A identidade histórica dos lotes LC1/LC2 sem CTA no plano padrão é preservada; repetir a confirmação encontra o lote já salvo.

Para emitir CTA, incluir `create_account` **dentro de um mapeamento de conta movimentada** em `accounts`. Exemplo de um único item desse objeto, com ID local fictício `123`:

```json
{
  "123": {
    "code": "789",
    "confirmed": true,
    "third_mode": "none",
    "create_account": {
      "destination_missing": true,
      "classifier": "1.01.001",
      "name": "Conta sintetica",
      "cost_center_mode": "0",
      "reconciliation": "0"
    }
  }
}
```

CTA usa classificador sem pontuação, completado com zeros à direita até 15 posições; nome até 30; terceiro `none/optional/required` → 1/2/3; centro 0/1/2/3; conciliação 0/1. Plano especial é opcional (`special_classifier`, até 20 posições, e `special_name`, até 80). Políticas são explícitas; campos obrigatórios não são inferidos do código local. Os fillers permanecem brancos. CTA só é emitido para contas efetivamente usadas e aparece antes de LC1/LC2; sua sequência é independente. Definições iguais no mesmo acesso são deduplicadas, mantendo a trilha dos IDs locais. Definições ou políticas conflitantes para o mesmo acesso e centro obrigatório ausente são recusados. Referências globais passam pela resolução de alias já existente antes do encoder; não se assume igualdade de IDs entre empresas.

Sem `create_account`, o TXT contábil permanece LC1/LC2. A prévia agora informa `account_registrations`, `record_counts`, `plan_code` e limites. A chave histórica de layout dos lotes foi mantida por compatibilidade; conferir os tipos efetivos em `record_counts`. Este recurso não importa TRC, não gera SLD nem substitui o intercâmbio de plano completo `CTBPLANO` que já existe.

## Integridade e operação

Prévia, confirmação e download não editam documentos, originais, fontes, lançamentos, partidas ou títulos. A confirmação grava apenas um lote de exportação imutável e auditoria na mesma transação. Nova fonte, valores/mapeamentos alterados ou plano diferente exigem prévia atualizada. Repetição e concorrência com o mesmo fingerprint encontram o mesmo lote. Isso **não impede duplicação no Prosoft se o operador reimportar o arquivo**; não há controle ou chamada à base de destino.

Exportar leitura é permitido com a competência aberta, fechada ou reaberta; os fechamentos continuam protegendo as alterações de escrituração pelos serviços existentes. O download fiscal só aceita lotes do layout fiscal da mesma empresa. O download contábil legado também revalida a permissão fiscal antes de servir um lote fiscal, impedindo usar a rota antiga para contornar a autorização.

## Validação e próxima homologação

Validação local: **295 testes de backend passaram em 123,890 s**, em 21 módulos: 30 novos e 265 regressões. Cenários novos cobrem offsets/formatos fiscais e CTA; desdobramentos e centavos; ausência de decisões; documentos não cobertos; datas/seleção/empresa; plano escolhido; todas as referências de origem; hash obsoleto; ASCII; replay/concorrência; rollback do lote e auditoria; permissões/CSRF; competência aberta, fechada e reaberta; hashes dos registros econômicos preservados; compatibilidade com fingerprints contábeis históricos. **138 testes de frontend e build Vite passaram**, com o aviso preexistente de chunk acima de 500 kB. Sintaxe dos seis arquivos Python alterados/novos e `git diff --check` passaram. Os comandos estão abaixo. A descoberta de testes do CI existente inclui automaticamente `tests/test_prosoft_increment.py`; nenhuma etapa de release/deploy é habilitada.

```bash
PYTHONPATH=tests:. python -m unittest test_prosoft_increment -v
PYTHONPATH=tests:. python -m unittest test_prosoft_increment test_business test_core test_journal_participants test_account_plans test_account_plan_codec test_global_account_plans test_lazy_account_refs test_fiscal_import test_fiscal_analytics test_fiscal_analytical_reports test_fiscal_series test_movement_exports test_operational_settings test_management test_workspace_context test_import_reprocessing test_import_payables test_import_package_cleanup test_reprocessing_linked_effects test_third_party_history -v
(cd frontend && npm ci --ignore-scripts && npm run build && node --test tests/*.test.js)
python -m compileall -q app/prosoft.py app/prosoft_fiscal.py app/business.py app/business_api.py app/permissions.py tests/test_prosoft_increment.py
git diff --check
```

As dependências DANFE exigidas pela aplicação foram disponibilizadas por diretório temporário de testes já existente no ambiente; o comando local de backend incluiu esse diretório no `PYTHONPATH`. Requisitos e arquivos lock da aplicação permanecem iguais. Não há lint configurado no repositório; foi feita verificação sintática e do diff.

Pendências para homologação: confirmar versão e rotina fiscal/contábil instaladas; conferir espécie e políticas cadastrais do destino; ensaiar TXT sintético de cada direção, desdobramentos, caracteres, brancos e plano escolhido; reconciliar quantidades/valores importados; testar reimportação/rollback numa base de homologação e registrar aceite. Não é necessário reenviar indiscriminadamente os layouts já disponíveis. Acesso ao Windows/RDP/Prosoft e comprovação de aceite desta versão continuam faltando.

Não executados: suíte integral do aplicativo, navegador deste incremento sem UI nova, PostgreSQL operacional, testes de escala, Prosoft/PVA/Windows, binários/instaladores, imagens e produção. CI remoto deve ser avaliado nos checks da PR. A primeira invocação ampliada citou dois nomes de módulos inexistentes; a rodada final acima usa os 21 módulos existentes e passou integralmente.
