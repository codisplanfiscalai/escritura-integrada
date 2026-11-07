# Contrato HTTP — Escritura Integrada

API JSON no prefixo `/api`, mesma origem do aplicativo. Valores recebidos são strings decimais com ponto (`"123.45"`); respostas monetárias são inteiros em centavos (`*_cents`). Erros têm `{detail: "mensagem em português", code: "..."}`. Listagens são arrays, exceto painel, competência e relatórios. Datas ISO `YYYY-MM-DD`; competência `YYYY-MM`.

## Sessão e contexto

- `GET /health` → `{status:"ok",version:"0.4.0-dev.1",demo:boolean}`.
- `GET /session` → `{authenticated,setup_required,demo,user:{id,username}|null,csrf_token,active_company_id,period}`.
- `POST /setup {username,password}` cria o primeiro administrador (senha mínima 12 caracteres), inicia sessão; disponível uma vez.
- `POST /login {username,password}`; `POST /logout {}`. Retorno de setup/login é a sessão.
- `POST /demo-login {}` apenas no modo de demonstração explícito; não existe credencial fixa em produção.
- `POST /context {company_id,period}` ativa empresa e competência **por sessão**; retorna sessão atualizada.

Cookies HTTPOnly/SameSite=Strict. Todas as mutações autenticadas exigem `X-CSRF-Token` recebido da sessão. Usar `credentials:'same-origin'`. Dados operacionais exigem autenticação. Escritas em `/companies/{id}/...` exigem que `id` seja a empresa ativa; divergência retorna 409 `stale_context`. Lançamentos contábeis e documentos fiscais devem pertencer à competência ativa. Cadastro/edição de empresa não muda o contexto, permitindo editar A com B ativa. Modais devem capturar empresa/competência ao abrir; não substituir o destino ao salvar.

## Empresas, contas e centros

- `GET /companies` → array de empresas.
- `POST /companies` → empresa. Campos: `code,name,trade_name,tax_id,regime,state,city,address,number,district,postal_code,ibge,ie,im,cnae,email,phone,prosoft_code`; `create_default_accounts` boolean explícito, padrão false.
- `PUT /companies/{id}` → empresa; campos acima e `version` obrigatória. Versão desatualizada: 409. CNPJ é texto numérico ou alfanumérico com dígitos verificadores; a verificação não consulta situação cadastral.
- `GET/POST /companies/{id}/accounts`, `PUT .../accounts/{account_id}`: `access_code,classifier,name,nature:'debit'|'credit',analytical:boolean,requires_cost_center:boolean,active:boolean,version` (version na edição).
- `GET/POST /companies/{id}/cost-centers`, `PUT .../cost-centers/{center_id}`: `code,name,active:boolean,version`.

## Escrituração

- `GET .../journals?period=YYYY-MM` → `[{id,company_id,number,date,period,document,history,total_cents,lines,reversal_of,reversed_by,...}]`.
- `POST .../journals {date,document,history,idempotency_key,lines:[{account_id,debit:"0.00",credit:"0.00",cost_center_id:null}]}` → lançamento. Cada linha tem somente um lado positivo, contas analíticas e centros da mesma empresa; débitos = créditos > 0. A mesma chave/conteúdo retorna o lançamento existente; conteúdo diferente retorna 409.
- `POST .../journals/{journal_id}/reverse {date,reason,idempotency_key}` gera lançamento inverso, nunca apaga o original.
- `GET .../documents?period=YYYY-MM` → array com `id,company_id,direction,number,series,model,issue_date,posting_date,partner_name,partner_tax_id,key,cfop,total_cents,taxes,items,status,version,journal_id,source`.
- `POST .../documents {direction:'incoming'|'outgoing',number,series,model,issue_date,posting_date,partner_name,partner_tax_id,key,cfop,total:"0.00",taxes:{},items:[]}` → documento `pending`.
- `PUT .../documents/{doc_id}` recebe campos do documento, `version` e `reason`. Disponível antes de `booked`; edição invalida revisão e retorna `pending`. Preserva original, hashes e metadados de origem. Verifica abertura fiscal da competência antiga e da nova. O corpo não substitui a origem preservada.
- `POST .../documents/{doc_id}/review {version,reason}` → documento `reviewed`.
- `POST .../documents/{doc_id}/book {version,reason,lines?:[...],idempotency_key?}` → `{document,journal}`. Sem linhas, escritura somente o fiscal; com linhas, contabilização explícita e atômica. Nenhum imposto ou conta é presumido. A revisão registra conferência humana e não certificação fiscal.

Para modelos 55/65/57, confira a classificação de escrituração: CFOP em cada item/registro analítico disponível, ou no documento quando ele não possui esse detalhamento. CFOP de origem permanece em `source_cfops`/`items[].source_cfop`. `taxes` preserva as chaves/textos da origem (por exemplo `ICMSTot/vICMS`, `VL_ICMS`), inclusive informação não monetária; não normalizar indiscriminadamente os campos. Documento manual pode registrar campos monetários explícitos adicionais. Não há cálculo automático ou correspondência presumida entre esses campos.

## Financeiro e conciliação

- `GET .../titles?kind=payable|receivable` → array com `id,kind,description,partner_name,document,issue_date,due_date,amount_cents,paid_cents,balance_cents,status:'open'|'partial'|'settled',version,document_id,settlements`.
- `POST .../titles {kind,description,partner_name,document,issue_date,due_date,amount:"0.00",document_id?:id}`.
- `POST .../titles/{title_id}/settle {date,amount:"0.00",reason,idempotency_key,lines?:[...]}` → `{title,settlement,journal}`. Valor não pode superar saldo. Linhas opcionais geram contabilização balanceada na data informada.
- `GET .../banks?period=YYYY-MM` → array `{id,bank_account,date,amount_cents,description,reference,external_id,reconciled,reconciliation}`.
- `GET .../banks/{transaction_id}/suggestions` → array `{title_id,description,amount_cents,date,difference_days,reason}` por valor, sentido e proximidade de data; não confirma vínculo nem baixa títulos.
- `POST .../banks/{transaction_id}/reconcile {title_id,reason}` → vínculo manual único. Exige correspondência de valor/sentido e título da empresa; não baixa automaticamente.
- `POST .../banks/{transaction_id}/unreconcile {reason}` remove vínculo operacional e registra auditoria.

## Importação

- `GET .../imports` → array de metadados (sem conteúdo bruto).
- `POST .../imports/preview {filename,content_base64,period,options?:{date_format,encoding,delimiter,decimal_separator,thousands_separator,bank_columns,posting_date},bank_account?:string}` → `{id,filename,sha256,preview_hash,status,period,documents:[],transactions:[],issues:[],sources:[],format,bank_account_hint?}`. Tamanho máximo do arquivo: 20 MiB. Original e resultado ficam preservados no banco. `posting_date` é data explicitamente escolhida para escrituração de XML; não altera a emissão. Divergência entre escrituração e competência bloqueia a confirmação.
- `GET .../imports/{import_id}` → a mesma prévia.
- `POST .../imports/{import_id}/confirm {preview_hash,bank_account?:string}` → `{import_id,status:'confirmed',documents_created,documents_duplicate,transactions_created,transactions_duplicate,document_ids,transaction_ids}`. Empresa/competência/prévia são conferidas novamente. Erros de interpretação bloqueiam confirmação. Avisos mantêm documentos pendentes. Para transações, conta bancária explícita é obrigatória. Confirmação é transacional e idempotente.

## Cadastros fiscais, regras e modelos

- `GET .../catalogs?kind=cfop|ncm|revenue|service` → array.
- `POST .../catalogs`, `PUT .../catalogs/{id}`: `kind,code,description,direction:'incoming'|'outgoing'|'both',valid_from,valid_to,source,active,version`.
- `DELETE .../catalogs/{id}?version=N` desativa com versionamento; não afirma validade legal de códigos.
- `GET .../rules` → versões atuais; `GET .../rules/{id}/versions` → histórico da família.
- `POST .../rules`, `PUT .../rules/{id}`: `name,tax,rate` (string percentual ou null), `direction,cfop,ncm,valid_from,valid_to,source,responsible,status:'draft'|'validated',version`. Edição cria nova versão e mantém anterior. Nenhuma alíquota é semeada.
- `DELETE .../rules/{id}?version=N` desativa por nova versão.
- `POST .../rules/{id}/simulate {date,base:"0.00"}` → `{simulation:true,legal_validation:false,rule_id,rule_version,base_cents,rate,result_cents,memory:[...]}`. Prévia matemática paramétrica, sem apuração legal nem alteração de documentos.
- `GET/POST /templates`: modelos reutilizáveis `{name,description,source_company_id,rule_ids:[]}`; `POST .../templates/{template_id}/apply {reason}` copia regras como rascunho para revisão da empresa destino.

## Competências, painel, relatórios e auditoria

- `GET .../periods?period=YYYY-MM` → `{period,fiscal:{module,period,status:'open'|'closed',closed:boolean,reason,version},accounting:{...}}`.
- `POST .../periods/close {period,module:'fiscal'|'accounting',reason}`; `POST .../periods/reopen` mesmo corpo. Retorna competência completa. Fechamentos independentes e verificados dentro da transação. Fiscal não fecha com documentos ainda pendentes/revisados na competência.
- `GET .../dashboard?period=YYYY-MM` → `{company_id,period,documents:{count,pending,reviewed,booked,total_cents},accounting:{journals,debit_cents,credit_cents},financial:{payable_cents,receivable_cents,overdue_cents},reconciliation:{total,pending,matched},periods:{...}}`.
- `GET .../reports/diary?period=&cost_center_id=` → `{kind:'diary',company_id,period,cost_center_id,rows:[{journal_id,number,date,document,history,account_id,access_code,classifier,account_name,debit_cents,credit_cents,cost_center_id,cost_center_name}],totals:{debit_cents,credit_cents}}`.
- `GET .../reports/ledger?period=&account_id=&cost_center_id=` → mesmo envelope; linhas acima acrescidas de `balance_cents`, `opening_cents`; saldo é débito menos crédito. Totais incluem `opening_cents,debit_cents,credit_cents,closing_cents`.
- `GET .../reports/trial-balance?period=&cost_center_id=` → `{kind:'trial-balance',company_id,period,cost_center_id,rows:[{account_id,access_code,classifier,account_name,nature,opening_cents,debit_cents,credit_cents,closing_cents}],totals:{opening_cents,debit_cents,credit_cents,closing_cents}}`.
- `GET .../audit?limit=100` → array `{id,company_id,actor,action,entity,entity_id,details,created_at}`.

Relatórios internos refletem exclusivamente os lançamentos registrados, incluindo estornos como novas partidas. Filtro por centro atua por linha; contrapartidas sem esse centro ficam fora do recorte. Não se apresenta o recorte como balanço geral nem livro fiscal homologado. A instalação inicial não contém empresas, códigos fiscais ou taxas. Modo de demonstração utiliza exclusivamente dados explicitamente fictícios de novembro de 2026.

## Extensões 0.5

Os endpoints anteriores são preservados. `app/business_api.py` e `tests/test_business.py` contêm os contratos executáveis das extensões. Em todos os caminhos abaixo, `...` corresponde a `/api/companies/{id}`.

| Operação | Endpoint e contrato |
|---|---|
| Consultas | `GET /api/lookups/{cnpj|cep}/{value}?provider=auto&refresh=false`; resposta com dados, provedor, data, cache e ressalvas. Nunca grava o cadastro automaticamente |
| Perfil cadastral | Empresas recebem `profile` com natureza/situação, complemento, CNAEs secundários, `ie_status` e `state_registrations`. Estados de IE são explícitos; informação ausente não se transforma em isenção |
| Cadastros | `GET/POST .../masters/{participant|establishment|product|service|history|accounting_model}`; `PUT .../masters/{kind}/{item_id}` com `version`. Corpo com `code,name,tax_id,active,data`; os campos de `data` são validados por tipo |
| Escrituração integrada | `POST .../documents/{id}/book` aceita `model_id` ou partidas explícitas e `generate_titles,installments`. Documento, parcelas e lançamento são gravados na mesma transação; totais devem coincidir |
| Rastreio/reversão | `GET .../documents/{id}/trace`; `POST .../documents/{id}/reverse {version,date,reason,idempotency_key}`. Baixas, vínculos e renegociações vinculadas precisam ser desfeitos antes |
| Saldos iniciais | `POST .../opening-balances {date,document,history,lines}`; partidas balanceadas e auditadas, sem alterar saldos históricos silenciosamente |
| Baixa | `POST .../titles/{id}/settle` acrescenta `version,interest,fine,discount`; `amount` é principal. Caixa = principal + juros + multa − desconto. Partidas opcionais devem representar todos os componentes |
| Estorno de baixa | `POST .../settlements/{id}/reverse {date,reason,idempotency_key}`; estorna o lançamento vinculado e recompõe saldo atomicamente |
| Renegociação | `POST .../titles/renegotiate {date,reason,idempotency_key,title_ids,versions,interest,discount,installments}`; `GET .../renegotiations`; `POST .../renegotiations/{id}/reverse {date,reason,idempotency_key}`. Reversão exige parcelas sem movimentos |
| Rateio bancário | `POST .../banks/{id}/allocate {reason,idempotency_key,settle,allocations:[{title_id,amount}]}`; `settle:false` só vincula, `true` baixa o principal explicitamente. `POST .../allocations/{id}/reverse {reason}` desfaz vínculo sem estornar baixa |
| Participantes | `GET .../partner-reconciliation`; títulos, pagamentos e saldos agrupados por identidade do participante |
| Relatórios | `GET .../business-reports/{kind}?start=YYYY-MM-DD&end=YYYY-MM-DD&account_id=&cost_center_id=&query=&status=&direction=&format=json|csv`; filtros aplicáveis a cada relatório, valores JSON em centavos e CSV decimal sem ponto flutuante |
| Pré-apuração | `GET/POST .../assessments`; consulta com `period`, criação com bases/documentos/regras revisados, efeito e justificativa. Resposta sempre explicita `legal_validation:false`, memória e fingerprint de origem |
| Ajustes | `GET/POST .../tax-adjustments`; `POST .../tax-adjustments/{id}/reverse {period,reason}`; sem exclusão da evidência original |
| Prosoft | `POST .../prosoft/preview`, `POST .../prosoft/confirm`: período, modo, mapeamentos e confirmações. Confirmação exige hash da prévia e aceite explícito de transliteração quando houver. `GET .../exports/{id}/download` retorna lote persistido |
| Originais | `GET .../imports/{id}/original`; arquivo original preservado, com nome seguro no download |
| Usuários | `GET/POST /api/users`, `PUT /api/users/{id}`; administrador gerencia papéis `admin/operator/viewer` e empresas autorizadas. Alterar acesso revoga sessões existentes |

Relatórios disponíveis: `diary`, `consolidated-diary`, `ledger`, `trial-balance`, `cost-centers`, `balance-sheet`, `income-statement`, `fiscal`, `financial`, `cash-flow`, `partners`. Os nomes de campos e regras completas dos corpos são documentados pela interface e pelos testes de contrato; dados sem revisão não recebem confirmação implícita.
