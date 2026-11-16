# Consulta preparatória de saldos observados Prosoft

`GET /api/companies/{cid}/prosoft/observed-balances?start=2025-01-01&end=2025-12-31`

Consulta JSON somente leitura, restrita a um exercício e à empresa e módulo
Contábil ativos. Não gera TXT, não habilita SLD no exportador e não certifica
abertura. SLD é formato próprio Prosoft, não SPED.

O procedimento [C52 da Alterdata](https://novoajuda.alterdata.com.br/prosoft/c52-procedimento-para-importacao-de-lancamentos-txt-prosoft-contabil)
orienta a abertura do exercício/sistema de origem e movimentos mensais. Não é
evidência de reaplicação segura nem de completude dos dados desta aplicação.

A consulta reutiliza o leitor `_snapshot` de `sped_generator/ecd_snapshot.py`
sob uma única transação de leitura. Reagrupa exclusivamente as partidas por
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
intervalo pode não resolver o excesso. O limite de resposta é verificado após a
projeção; não há paginação, processamento em streaming ou certificação de volume
máximo em produção. Não há alterações de schema ou operações de escrita.

Validação: `PYTHONPATH=tests:. python -m unittest test_prosoft_balances -q`.
Fixtures exclusivamente sintéticas. A comparação integral do dump do banco
antes/depois da consulta inclui tabelas de sessões, auditoria e referências.
