# PR67: coleta determinística das leituras de paginação

## Falha e evidência

O CI [43973435071](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43973435071),
head `838740ee633a5e5dd9c61b7bd09c79e6491f9b1d`, falhou no job Linux
`133671223495`, etapa «Validar desempenho e paginação no Chromium».
A medição `accounts` não continha a leitura exigida pela asserção de uma única
requisição paginada. Entretanto, o vetor completo de requisições do mesmo relatório
e o log do servidor continham exatamente um GET de contas com `page=1`,
`per_page=50`, status 200 e corpo decodificado de 12.748 bytes. A tela já exibia
as 50 linhas exigidas. As etapas PostgreSQL e Prosoft Chromium desse run passaram.

A causa está na instrumentação: o callback `requestfinished` chamava
`request.response()` e `response.body()` antes de adicionar a entrada ao vetor.
Essas chamadas síncronas do Playwright podem devolver o controle ao cenário
antes de o callback terminar. A cópia da medição era então feita sem a entrada,
que aparecia mais tarde no relatório completo. A prontidão da tabela não prova
que o observador Python concluiu; `networkidle` em uma SPA também pode referir-se
à navegação anterior.

## Reprodução e controle negativo

Em banco descartável exclusivamente sintético, com 22.597 contas e 183 títulos:

1. No script original do head acima, envolver `playwright.sync_api.Response.body`
   e atrasar somente a primeira resposta `/accounts?page=1&per_page=50&search=`
   em 500 ms com `response.frame.page.wait_for_timeout(500)` antes de chamar o
   método original reproduziu a mesma falha. A medição perdeu a leitura, embora
   o servidor tenha atendido um único GET 200. Não houve atraso na resposta do
   produto: somente no observador do teste.
2. O mesmo atraso, aplicado ao script corrigido, passou com um GET 200 de 12.748
   bytes na medição. A execução normal também passou. Os atrasos são controles
   diagnósticos locais e não integram o runner nem o workflow.
3. Como controle negativo, o wrapper do primeiro corpo disparou uma segunda
   leitura real com `response.frame.page.evaluate` e `fetch(response.url)`.
   A correção rejeitou o cenário: duas leituras GET 200, ambas de 12.748 bytes.
   A exigência de uma leitura não foi removida ou flexibilizada.

## Correção

`RequestMetrics` registra a entrada no evento `request`, captura o tempo de
conclusão e enfileira a requisição em `requestfinished`, sem RPC no callback.
O cenário principal drena a fila e decodifica os corpos antes de copiar cada
medição. Eventos adicionais disparados durante a decodificação são registrados
e a fila continua sendo drenada. Assim, uma duplicata iniciada já participa da
contagem, mesmo antes de seu corpo ser coletado. Falhas de leitura não são ocultadas.

As leituras esperadas de contas e dos catálogos preguiçosos do modal usam
`expect_request_finished`, instalado antes da ação, e verificam status 200.
Não se chama mais `Response.finished()`: na versão 1.62.0 instalada, esse método
cria uma tarefa de espera pelo fechamento do alvo que pode sobreviver à conclusão
da resposta e emitir `Target closed` no encerramento. Os dois controles positivos
corrigidos e o controle negativo não emitiram essas mensagens. A conclusão HTTP
continua sendo exigida pelo evento de requisição finalizada.

O gate continua exigindo exatamente um GET de contas, agora verificando `page=1`
por parsing da query, status 200, corpo maior que zero e menor que 100.000 bytes,
sem carregar lançamentos, centros de custo ou histórico. Permanecem os controles
de 50 linhas, total de contas, busca acentuada, segunda página, paginação dos
183 títulos, consultas preguiçosas e ausência de erros HTTP/JavaScript.
Não foram adicionados retries, sleeps, aumento de timeout ou mudanças no produto,
frontend, dependências ou workflow.

## Verificações efetivas e limites

- 211 testes backend passaram, sem falhas, erros ou skips, incluindo evidência,
  paginação/desempenho, TRC, exportação fiscal/contábil, referências, canceladas,
  contexto, terceiros, saldos e composição. Os cinco novos testes do coletor
  cobrem reentrância, duplicata pendente, falha de corpo e gates negativos.
- 204 testes frontend passaram, sem falhas ou skips.
- Chromium local 141.0.7390.37, driver Playwright 1.62.0: cenário normal de
  desempenho/paginação e cenário com atraso do observador passaram; duplicata
  intencional reprovou. Os 14 grupos do cenário Prosoft/TRC passaram, sem erros JS.
- O CI usa Chromium 151.0.7922.34. Sua instalação local falhou por arquivo ZIP
  inválido/truncado no download (`End of central directory record signature not
  found`). Não foi contornado o erro. Essa versão precisa ser validada pelo novo CI.
- Sem novo build frontend nesta correção, que não o modifica. Não executados aqui
  suíte integral, PostgreSQL real, instaladores/imagens, carga real ou importação
  no Prosoft. As verificações locais usaram o frontend já construído da PR67.
- Correção testada sobre o head da PR, com base `4610314bc94abbbcecaf271c0e87ca04623525d3`.
  Ao preparar a publicação, develop estava em `a31f717f3e037cc4e33fddabcdd2f6fc3f3ee5cc`.
  `git merge-tree --write-tree` confirmou composição textual sem conflitos; a
  branch não recebeu merge de develop nesta correção. CI e composição final
  continuam sujeitos à coordenação antes do merge.

Somente código, testes e este diagnóstico sanitizado acompanham o commit.
Relatórios, capturas, bancos e logs permanecem fora do Git. Sem dados reais,
acesso a produção/Windows/RDP, implantação, transmissão ou homologação no Prosoft.
