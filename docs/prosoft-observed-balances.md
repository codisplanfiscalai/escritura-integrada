# Consulta preparatória de saldos observados Prosoft

`GET /api/companies/{cid}/prosoft/observed-balances?start=2025-01-01&end=2025-12-31`

Consulta JSON somente leitura, restrita a um exercício e à empresa e módulo
Contábil ativos. Não gera TXT, não habilita SLD no exportador e não certifica
abertura. SLD é formato próprio Prosoft, não SPED.

O procedimento [C52 da Alterdata](https://novoajuda.alterdata.com.br/prosoft/c52-procedimento-para-importacao-de-lancamentos-txt-prosoft-contabil)
orienta a abertura do exercício/sistema de origem e movimentos mensais. Não é
evidência de reaplicação segura nem de completude dos dados desta aplicação.

A consulta reutiliza o leitor `_snapshot` de `sped_generator/ecd_snapshot.py`
sob uma única transação de leitura, com `include_balances=False`. Essa opção
omite a construção dos resumos ECD `monthly_balances` e
`opening_history.recorded_balances` e identifica a omissão com
`derived_balances_omitted=true`; o padrão ECD continua incluindo os resumos.
Os hashes individuais de lançamentos e suas origens são preservados. O hash do
snapshot de origem passa a identificar essa variante sem resumos, portanto não
é igual ao hash da variante completa. Reagrupa exclusivamente as partidas por
`account_id`, `participant_id` da partida e `cost_center_id`. IDs nulos são
preservados; códigos iguais não unem entidades. O escopo da empresa faz parte
da resposta. As permissões de consulta de Prosoft, lançamentos, contas e centros
são revalidadas junto da sessão, usuário ativo, empresa, módulo e exercício na
mesma leitura. Permissão de catálogo global de terceiros não concede acesso.
Não há consulta nem exposição de nomes/documentos cadastrais de terceiros.

`prior_history_balances` soma partidas anteriores ao início, inclusive exercícios
anteriores, sem convertê-las em abertura oficial. `monthly_balances` informa
acumulado observado anterior, débitos, créditos e acumulado posterior (débito
menos crédito), todos com centavos e decimais em strings exatas. O fechamento
observado de um mês sem partidas pode transportar o acumulado anterior; isso
não significa movimento, inatividade ou completude. Frações de mês preservam
os limites solicitados. Reversões conservam original, estorno e seus vínculos.
`journal_evidence` preserva IDs de linhas, datas, referências de origem e eventos
de auditoria; o hash de origem refere-se ao registro completo do leitor, não à
projeção reduzida. Nenhum hash representa atestado contábil ou validação Prosoft.

Abertura oficial e mapeamentos de destino ficam nulos; integridade histórica,
atestação de abertura e reaplicação segura ficam desconhecidas. Geração SLD fica
bloqueada incondicionalmente, inclusive para banco vazio ou aritmética zerada.

A leitura falha com HTTP 413, sem resultado parcial, quando qualquer coleção
lida pelo snapshot excede 10.000 registros, os resultados JSON de importações
contábeis somam mais de 2.000.000 caracteres ou a resposta supera 16 MB UTF-8.
Os limites de coleções incluem evidências históricas e metadados: diminuir o
intervalo pode não resolver o excesso.

Há também teto cumulativo de 20.000 linhas de saldos mensais projetados. Antes
de construir os movimentos e saldos de cada mês, a consulta conta a união dos
grupos acumulados com os grupos das partidas daquele mês. Cada grupo carregado
para outro mês consome outra linha, inclusive em meses sem lançamentos. O mês
que excederia o teto é recusado com HTTP 413 antes da construção desse lote;
nenhum mês previamente calculado é devolvido como resposta parcial. Exatamente
20.000 linhas são permitidas, sujeitas aos demais limites.

Antes de chamar o leitor compartilhado, há também um orçamento agregado de
1.000.000 bytes dos campos textuais carregados: cadastro da empresa
(inclusive `profile_json`), contas efetivas e hashes dos planos, vínculo do plano,
centros, datas/documento/histórico/autoria dos lançamentos, eventos de auditoria e
layout/fingerprint/resultados das importações contábeis. A medição usa agregações
SQL `LENGTH(CAST(... AS BLOB))` na mesma transação; apenas os totais numéricos
são materializados. A contagem inclui NUL e mede os bytes na codificação do
banco SQLite (UTF-8 nos bancos criados pela aplicação), não caracteres. O inventário explícito de colunas deve acompanhar mudanças nos SELECTs
do leitor. Dados fiscais/financeiros não carregados por esse leitor não entram.
Excesso retorna HTTP 413 antes de chamar `_snapshot`, inclusive com poucas linhas.

O limite anterior de 2.000.000 caracteres de resultados importados é mantido
separadamente; caracteres não são bytes. Nenhum dos dois representa memória de
objetos: JSON decodificado, textos repetidos nos candidatos/hash e serialização
acrescentam custo. Não há garantia rígida de RAM,
limite de tempo de consulta ou streaming. O teto de 16 MB UTF-8 da resposta ainda
é verificado depois da projeção e serialização. A via Prosoft já não constrói os
resumos ECD descartáveis; seu próprio teto incremental de 20.000 linhas continua
ativo. Não há paginação, certificação de carga de produção, alterações de schema
ou operações de escrita. O preflight protege a chamada ao leitor contábil; não
limita leituras anteriores do middleware, como cadastro/configuração da empresa
na resolução da sessão.

Validação: `PYTHONPATH=tests:. python -m unittest test_prosoft_balances -q`.
Fixtures exclusivamente sintéticas. A comparação integral do dump do banco
antes/depois da consulta inclui tabelas de sessões, auditoria e referências.
