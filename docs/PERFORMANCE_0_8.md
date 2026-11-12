# Desempenho das consultas na linha 0.8

## Origem e limites

Esta implementação foi reconstruída sobre `420d35a4cf4b0e259c75a3d2822c36861b10e283` (0.8.0-dev.22). Os checkouts e o commit local anterior não estavam mais disponíveis. Os commits e testes desta entrega são novos; não são apresentados como recuperação do código anteriormente testado.

A investigação da dev.22 identificou bloqueios compartilhados de carregamento:

- Financeiro aguardava títulos, plano inteiro, documentos, participantes e renegociações para exibir os títulos.
- A paginação do plano era apenas visual: o navegador recebia todas as contas.
- Trocas de contexto acionavam leituras da tela anterior antes de sua desativação.
- A biblioteca global permanecia reagindo a mudanças mesmo fora da tela.
- Cadastros fiscais, históricos e relatórios não contábeis baixavam catálogos contábeis desnecessários.
- O resumo da biblioteca transferia BLOB original e JSON integral do SQLite para Python apenas para contar registros.

As observações na instalação real não são medições precisas de endpoints. A estrutura aparecia antes dos dados e foi observada uma falsa indicação inicial de zero títulos. Os tempos entre chamadas da ferramenta não podem ser usados como latência real nem comparados diretamente com estes benchmarks sintéticos. Nenhuma base real foi modificada para esta implementação.

## Mudanças

- `/accounts` conserva a resposta completa quando `page` não é informado. Com `page`, retorna `{items,total,page,per_page}`, usa leitura consistente, `COUNT` e `LIMIT/OFFSET`; limites válidos de 1 a 5.000 registros por página.
- Pesquisa do plano por acesso, classificador e nome, sem distinguir caixa ou acentos. `%` e `_` são caracteres literais, não curingas SQL. Contas locais e referências compartilhadas mantêm IDs, propriedades, isolamento por empresa e ordem. Consultar não materializa contas globais.
- Plano de contas pede somente a página exibida. A pesquisa tem debounce de 180ms, reinicia na primeira página e a paginação ajusta páginas inválidas após mudanças nos dados.
- Contas a pagar/receber carrega apenas títulos. Os documentos e participantes chegam ao abrir um novo título, renegociações ao abrir seu histórico, e contas ao solicitar integração contábil de uma baixa. Falhas oferecem retry e bloqueiam salvar até a carga necessária terminar.
- Financeiro exibe até 50 linhas inicialmente, aceita até 5.000 por página e conserva seleção e saldo sobre o conjunto completo. Loading, filtros e fim das páginas são explícitos.
- Cargas automáticas são coalescidas até a troca de tela terminar. Respostas antigas, telas desativadas e contexto em transição não atualizam a tela atual.
- Consultas carregam somente os catálogos necessários; os fluxos contábeis que realmente usam o plano completo continuam compatíveis. Formatadores monetários são reutilizados.

## Validação reproduzível

```sh
python -m pip install -r requirements-test.txt
npm --prefix frontend ci
npm --prefix frontend run build
python -m scripts.ci.checks --version "$(cat VERSION)" --source-sha "$(git rev-parse HEAD)" --output artifacts/performance/linux-checks.json
python scripts/benchmark_workspace.py --output artifacts/performance/after.json
python scripts/benchmark_workspace.py --repo /caminho/checkout-base --label before --output artifacts/performance/before.json
python scripts/browser_performance.py
```

O benchmark cria um diretório temporário demonstrativo com 22.591 contas compartilhadas e seis locais (22.597), mais 183 títulos sintéticos a pagar. Mede serialização HTTP pelo TestClient, sem rede ou renderização. O cenário Chromium usa a mesma fixture em servidor isolado, rede simulada de 80ms/512KiB/s, registra chamadas/tamanhos/tempo até os dados e verifica paginação, pesquisa, histórico, cancelamento e retorno entre módulos. Não mede a infraestrutura do usuário.

O gate Chromium bloqueia pedidos de catálogos indevidos e respostas acima de 100KB para a primeira página de contas. Em falha, captura screenshot, HTML e texto antes de fechar a sessão. Erros secundários de evidência ou limpeza não substituem o traceback original, e falha de limpeza também bloqueia sucesso. Evidências ficam em `artifacts/performance/`, separadas dos demais cenários de browser.

A execução local de navegador não foi repetida após a restrição anterior do ambiente. A validação gráfica real e dos pacotes depende do CI para o commit publicado. Uma aprovação de testes unitários/build não equivale a um passe de Chromium nem a homologação em produção.
