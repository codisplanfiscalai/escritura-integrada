# Integração Contábil — entradas e saídas

## Inventário e base

A PR39 já integrada oferecia configuração por empresa e geração atômica de saídas individuais ou efetivamente consolidadas por dia, classificação e contas/dimensões. A PR42 acrescentou seleção, execução e rastreabilidade, mas sua tela e o serviço de lote recusavam entradas. O fluxo antigo de contabilização por documento já aceitava ambos os sentidos. Não existia prévia contábil do lote nesta tela; as prévias de importação e de modelos pertencem a outros fluxos.

O incremento começou na develop `87b913990d8dc6160734c5b1f8046f6af9feb44f`, dev.20, após confirmar PR39, PR42 e PR41 mescladas e PR40/43/44 abertas. Durante a validação a PR43 foi integrada: a composição final incorpora por merge a develop **`3c8aa7158e6bfcc8710739b08ddc9bf58c0fb1a5`**, dev.21. O catálogo SPED e suas permissões foram preservados. Não houve escrita nas branches de PR40/43/44.

Não há `AGENTS.md` nem `.agents/skills` no checkout. A worktree é isolada; o trabalho anterior permanece preservado. Não foram consultados dados reais, backups, XMLs de usuários, logs privados ou ambientes de produção.

## Comportamento entregue

- **Fiscal → Integração Contábil** e **Contábil → Integração Fiscal** abrem o mesmo componente e os mesmos serviços. Cada acesso usa o contexto/permissões do módulo; não existe um segundo processo de geração. A troca entre acessos recarrega os vínculos persistidos.
- O seletor de sentido separa entradas e saídas e limpa seleção, resultado, rastreabilidade e prévia ao mudar. Não permite misturar sentidos no mesmo lote. Empresa, exercício, módulo e sentido identificam a consulta assíncrona; respostas antigas não substituem o contexto atual.
- **Saídas** mantêm a configuração persistida individual/diária, sem migração de chave, valor padrão ou versão. Consolidação diária continua criando lançamentos reais por data de escrituração, classificação e contas/dimensões. Seleções posteriores criam complementos, sem reescrever o histórico.
- **Entradas** são sempre **individuais**, um lançamento por nota, inclusive se o modo das saídas for diário. Não há opção de consolidação de entradas e consultá-las/gerá-las não salva nem muda o modo das saídas. A versão existente da configuração é conferida para evitar parâmetros obsoletos.
- Cada nota exige modelo explicitamente selecionado, ativo, revisado, compatível com o sentido e vigente na escrituração. A UI oferece somente modelos desse sentido ou `both`; o servidor revalida dentro da operação. As contas são exclusivamente as configuradas no modelo/plano da empresa, inclusive plano global ou próprio. Não se infere conta de compra/venda, classificação, participante ou saldo. Fornecedor exigido pelo serviço existente deve estar explicitamente vinculado.
- A competência continua sendo a da escrituração, independente da emissão. Fechamento fiscal/contábil é respeitado; alterações exigem reabertura. Não foi acrescentada certificação, frase de confirmação, autorização fiscal ou outra trava operacional.

## Prévia independente e somente leitura

**Consultar prévia contábil** é opcional. Usa o mesmo planejador/validador da execução, com conexão de leitura em snapshot e sem materializar referências de contas, gravar auditoria/idempotência, criar títulos ou vincular documentos. Mostra quantidade prevista, datas, notas de origem, valores, contas de débito/crédito e dimensões configuradas. Saídas diárias são apresentadas nos mesmos grupos que seriam efetivamente gerados; entradas ficam separadas.

Fechar a prévia não executa nem cancela uma contabilização já realizada. Mudar seleção, modelo, histórico, configuração, filtros ou contexto invalida a prévia; cancelar uma leitura descarta também sua resposta tardia. Erros não são mostrados como sucesso. Não é uma reserva de dados nem um token obrigatório de aprovação: executar revalida os dados atuais na transação. Revogação de modelo/permissão e competência fechada após a consulta são rejeitadas pelo domínio.

O Diário Consolidado continua sendo relatório independente, somente leitura, sobre lançamentos existentes. A prévia de uma seleção também não altera esse relatório nem transforma sua agregação visual em movimento contábil.

## Transação, repetição e rastreabilidade

O serviço de saídas foi estendido pontualmente com o sentido e uma ramificação de prévia; entradas e saídas reutilizam normalização, resolução de contas, validação de modelos, geração de partidas e controle de fechamento. Não houve refatoração de core/API/listagem/dashboard/SPED.

Saídas conservam o escopo/chaves idempotentes anteriores. Entradas usam escopo `fiscal-purchases-accounting` e prefixo de lançamento `purchases:` separados, preservando a semântica de repetição. As associações existentes impedem duplicação mesmo ao usar outra chave, trocar modo/menu ou reprocessar seleção. A operação inteira é atômica. Concorrência com a mesma intenção tem um único efeito.

A UI conserva também o endpoint no pedido pendente, além do contexto, corpo, modelos, versões e chave. Após resultado incerto, **Repetir a mesma solicitação** envia a mesma intenção. Atualizar a consulta verifica o estado persistido; abandonar uma consulta/prévia não produz movimentos. O editor global continua protegendo o contexto durante uma mutação em curso.

As contribuições de entradas usam a trilha histórica existente (`sales-accounting-source`/`sales-accounting-reversal`, nomes técnicos mantidos por compatibilidade), com `direction`, IDs, valores, hash de origem, modelo e partidas. O leitor histórico de origens é compartilhado. Estorno continua pelo documento, com compensação rastreável e proteção contra estorno direto do lançamento; o controle de evidência ausente agora reconhece também o prefixo de entradas. Cancelamento/reversão e reescrituração utilizam os serviços existentes. Limpeza de lotes e retenção de XML não foram alteradas e não excluem lançamentos.

## API e permissões

| Operação | Rota relativa à empresa | Permissão principal |
| --- | --- | --- |
| Configuração persistida das saídas | `/fiscal-sales-accounting/settings` | `accounting.accounts`: leitura/edição |
| Prévia de saídas | `/fiscal-sales-accounting/preview` | `accounting.journals`: leitura |
| Execução de saídas | `/fiscal-sales-accounting/generate` | `accounting.journals`: criação |
| Prévia de entradas | `/fiscal-purchases-accounting/preview` | `accounting.journals`: leitura |
| Execução individual de entradas | `/fiscal-purchases-accounting/generate` | `accounting.journals`: criação |
| Origens de qualquer lançamento da integração | `/fiscal-sales-accounting/journals/{id}/sources` | leitura de lançamentos e documentos |

Prévia/execução também exigem leitura de documentos fiscais e modelos contábeis. A tela exige leitura de contas para consultar a configuração. A API de prévia pode ser consultada por usuário com leitura sem criação; a seleção/geração da tela mantém a permissão de criação já existente. POSTs preservam autenticação, CSRF, empresa ativa, módulo/exercício e autorização contextual. O serviço revalida permissões da operação; notas/contas/modelos de outra empresa não são reaproveitados.

O corpo da prévia usa os mesmos `entries` (documento/versão/modelo), `settings_version` e histórico opcional da geração. Não exige chave idempotente porque não grava. A execução exige sua chave como antes. O limite técnico existente é de 1000 notas por solicitação, sem truncar seleção.

## Validação e limites

Resultados na composição dev.21:

- **607 testes backend/infraestrutura em 43 módulos: OK**, sem falhas/erros/skips, 232,139 s incluindo carregamento. Incluem 12 testes novos de entradas/prévia e as regressões de saídas, consultas otimizadas e SPED/catálogo de obrigações.
- **164 testes frontend: OK**, 2,923 s. Quatro testes novos exercitam o componente real compilado: sentido/modelos/endpoint, repetição de entrada com a mesma intenção, prévia cancelada e respostas antigas; os menus são conferidos no App.
- **Build Vite dev.21: OK**, 4,27 s; bundle principal 819,90 kB, gzip 243,34 kB, com o aviso preexistente de chunk acima de 500 kB. Dependências do produto não foram alteradas.
- **Três roteiros Chromium 141: OK**, 17 grupos (integração=7, contexto=6, totalizadores fiscais=4), zero erros JavaScript. A prévia e seu fechamento não alteraram hashes de documentos/lançamentos/partidas/títulos/auditoria. Duas entradas de 0,01 e 10,02 ficaram individuais; duas saídas desses valores geraram um lançamento diário de 10,03.
- Nos dois sentidos, a resposta foi interrompida após o commit do servidor e a repetição conservou corpo/chave e todos os hashes. O acesso pelo outro menu também não duplicou movimentos. Resultado sintético final: empresa A=8 e B=2 lançamentos, todos balanceados, sem falhas de FK; lançamento/título anteriores e campos fiscais preservados. Modelo de entrada foi explicitamente configurado para despesas/fornecedores no cenário de navegador.
- Sintaxe Python, compilação Vue e `git diff --check`: OK. Conferência visual de configuração, prévia com contas e viewport de 1100 px. Nenhum diff em `app/core.py`, `app/api.py`, listagem/dashboard ou `app/sped_generator` contra a develop testada.

Comandos principais: `npm ci --ignore-scripts`, `npm run build` e `node --test tests/*.test.js` em frontend; runner `unittest` dos 43 módulos listados no JSON com `ESCRITURA_DATA_DIR=TemporaryDirectory`, `ESCRITURA_DEMO=0` definidos antes de importar a aplicação; `scripts/browser_fiscal_sales_accounting.py`, `scripts/browser_workspace_context.py` e `scripts/browser_document_summary.py` usando Playwright/Chromium e DANFE em diretórios de teste isolados já disponíveis. Infraestrutura é simulada nos seus testes; nenhum servidor de usuário foi operado.

Os resultados exatos e hashes sintéticos estão em [evidence/fiscal-incoming-accounting.json](evidence/fiscal-incoming-accounting.json). A suíte inclui os testes de entradas e regressões de saídas, permissões, contas globais/próprias, competência, vínculos, reprocessamento, estorno, consultas otimizadas, relatórios e SPED. O roteiro Chromium já registrado no CI foi ampliado para os dois menus e entradas, sem editar workflows.

A integração permanece **parcial**: aplicação automática do modo na importação, distribuição contábil por itens/classificações e ligação dos botões individuais anteriores ao novo lote seguem pendentes. Esses limites continuam explícitos na tela; modelos contabilizam o total da nota. A consulta anual/paginação local e o limite de 1000 notas foram preservados; não houve medição de escala ou homologação em tecnologias assistivas/dispositivos completos.

Não foram executados suíte integral do repositório, PostgreSQL operacional, instaladores/imagens, PVA/Prosoft, transmissão de obrigações ou instalações reais. O build mantém o aviso já conhecido de bundle acima de 500 kB; não há lint separado configurado. Publicação de código/PR não é implantação: sem merge final, release, deploy, Atlas ou produção.
