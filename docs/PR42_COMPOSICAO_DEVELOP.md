# PR42 — atualização com develop após a integração da PR39

A atualização elimina o conflito que impedia combinar a interface da PR42 com o backend já integrado. Foi preparada por merge, em worktree isolada, sem rebase ou force push. A própria PR42 passa a apontar para develop; não é criada outra PR nem executado o merge final.

## Referências verificadas

| Referência | SHA |
| --- | --- |
| Head público original da PR42 | `8a74a6846004f6d5e0bb14f4c334edd49405f3a3` |
| Merge da PR39 em develop, já concluído antes desta tarefa | `ee24f21f0199ac3b4ad2faca7ad6a1551fb9cbec` |
| **develop composta e testada** | **`34e816c798daf4f2cb30aaac188065599f912cce`**, `0.9.0-dev.14` |
| CI anterior da PR42 | [43690988098](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43690988098), concluído com sucesso no head original |

O primeiro pai do merge de atualização é o head original da PR42; o segundo é a develop acima. A publicação confere o head remoto esperado e rejeita alterações concorrentes, sem forçar a referência. A PR39 já integrada não é modificada e develop não recebe gravação nesta tarefa.

## Conflito resolvido sem alterar funcionalidades

O único conflito textual estava em `.github/workflows/ci.yml`: duas frentes haviam acrescentado bases diferentes à lista de PRs aceitas pelo CI. A resolução usa a **união das duas listas**, mantendo as bases de migração, SPED e integração contábil. Nenhuma regra de CI anterior é removida.

Uma comparação semântica do YAML confirma que, retirando apenas os dois passos originais da PR42 (navegador da integração e upload de seus artefatos) e a base adicional, o workflow é igual ao da develop. Jobs, comandos anteriores, pins e `contents: read` permanecem intactos; não são acrescentadas permissões de publicação nem gatilhos de release/deploy.

Preservação de fontes:

- Os **111 arquivos rastreados do backend `app/`** permanecem byte a byte iguais à develop testada, incluindo a contabilização integrada pela PR39, consultas otimizadas e SPED. Não há novas restrições operacionais ou refatoração de domínio.
- `FiscalSalesAccountingView.vue`, seu teste, seu roteiro de navegador e `App.vue` permanecem byte a byte iguais ao head original da PR42. A tela mantém configuração por empresa, seleção por filtros/páginas, modelos explícitos, intenção idempotente, contexto assíncrono e rastreabilidade.
- O relatório sintético continua somente leitura e independente da geração contábil. Mudança de modo não reescreve lançamentos anteriores; novas seleções geram complementos conforme a API existente.

Hashes e resultados estão em [evidence/pr42-develop-composition.json](evidence/pr42-develop-composition.json). Os testes foram executados antes do commit sobre a árvore já composta; o `source_sha` do roteiro antigo de contexto registra seu HEAD original, enquanto os hashes da interface e o manifesto do backend identificam o código efetivamente testado.

## Resultados locais

- **585 testes backend/infraestrutura em 41 módulos: OK**, sem falhas, erros ou skips. Runner: **221,017 s**; com carregamento: **222,338 s**. Incluem geração individual/diária, centavos, rastreabilidade, concorrência/idempotência, estorno parcial, troca de modo, competência fechada/reaberta, múltiplas empresas/contas/classificações, reprocessamento, limpeza de pacotes, consultas otimizadas, SPED e permissões.
- **156 testes frontend: OK**, em **3,069 s**, incluindo os 15 testes da interface e as regressões de indicadores/competência da develop.
- **Build Vite dev.14: OK**, mantendo o aviso existente de chunk acima de 500 kB; bundle principal 810,90 kB. Dependências da aplicação não foram modificadas.
- **Três roteiros Chromium headless 141 com aplicação local e SQLite descartável: OK**, sem erros de JavaScript. São seis grupos da integração contábil, seis de contexto/indicadores e quatro dos totalizadores fiscais.
- A interface gerou um agregado de 10,03 a partir de 0,01 + 10,02; a resposta foi interrompida depois do commit e a repetição enviou a mesma chave/corpo sem nova gravação. Todas as notas foram rastreadas. Geração individual com datas/CFOP/contas distintos, outra empresa, modo persistido, fechamento/reabertura e integridade de FK/balanço passaram. Resultado do cenário: empresa A=6 e B=2 lançamentos.
- Os hashes de documentos, lançamentos, partidas, títulos e auditoria permaneceram iguais na repetição e nas consultas/relatórios. Campos fiscais, título e lançamento anterior foram preservados. Filtros, páginas, KeepAlive, respostas fora de ordem e viewport de 1100 px também foram verificados.
- Sintaxe Python/YAML, compilação Vue, paridade de versões e `git diff --check` conferidos. Não há lint separado configurado na base.

Todos os testes usam fixtures sintéticas e diretórios temporários, com `ESCRITURA_DATA_DIR` definido antes de carregar a aplicação global. Os testes de infraestrutura simulam subprocessos/artefatos; não executam migração de uma instalação Docker. Playwright/Chromium e DANFE foram usados nas instalações isoladas de teste já preparadas, sem alterar dependências do produto.

A lista exata de módulos e os resultados/hashes dos navegadores constam no JSON de evidência. Comandos principais:

```sh
cd frontend
npm ci --ignore-scripts
npm run build
node --test tests/*.test.js
cd ..
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-sales-browser-deps:/tmp/escritura-daily-test-deps:. \
  python scripts/browser_fiscal_sales_accounting.py
```

Os roteiros adicionais são `scripts/browser_workspace_context.py` e `scripts/browser_document_summary.py`, com `ESCRITURA_TEST_BROWSER` apontando para o executável headless de teste. A suíte backend usa a lista dos 41 módulos do JSON e `TemporaryDirectory`/`ESCRITURA_DATA_DIR`/`ESCRITURA_DEMO=0` antes do carregamento de `unittest`.

## Escopo restante

A integração **continua parcial**: importação automática, distribuição contábil por itens/classificações e ligação dos botões individuais anteriores seguem pendentes, conforme o aviso já existente na interface. Esta atualização não amplia essa cobertura funcional.

Não foram executados a suíte integral do repositório, PostgreSQL operacional, PVA/Prosoft, instaladores/imagens, escala ou instalações reais. O novo CI deve ser conferido no SHA publicado; o sucesso do CI anterior não substitui os checks da atualização. Não houve leitura/publicação de dados reais, backups do usuário ou logs privados, nem produção, merge final, release ou implantação.
