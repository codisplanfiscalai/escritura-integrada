# Subguias da integração fiscal e contábil

Base testada: `develop` em `cd0a7ed05a2b6f336cccd4b3788b70d860fb0a24`, versão `0.9.0-dev.36`.

A consulta exibia configuração e avisos permanentes antes das notas, deixando a ação da seleção depois de toda a grade. A mesma view agora usa o componente existente `SectionTabs`, sem alterar API, domínio, permissões ou consultas contábeis.

- **Notas e seleção:** filtros, seleção, grade e paginação. O resumo com quantidade, valor e acesso a **Contabilizar seleção** fica antes da grade.
- **Contabilizar:** contas diretas, modelos opcionais, histórico, prévia, execução e resultado. Uma solicitação sem resposta confirmada continua acessível e só repete a seleção/chave já capturada.
- **Parâmetros e ajuda:** modo persistido das saídas e explicações de seleção, competência e cobertura.

Sentido e competência ficam em uma faixa compacta comum. O cabeçalho é **Integração Contábil** no Fiscal e **Integração Fiscal** no Contábil. Ambos continuam usando a mesma funcionalidade. Entradas permanecem individuais; saídas preservam o modo individual ou diário e todos os critérios existentes de agrupamento.

Os painéis usam `v-show`: navegar entre subguias mantém seleção, contas, histórico e prévia, sem recarregar referências. Troca de empresa, exercício, sentido ou filtros mantém a limpeza de contexto já existente; a consulta retorna a Notas nos resets de contexto. Cancelar uma consulta de prévia usa o descarte/abort existente, sem escrita e sem permitir resposta atrasada. Não há nova confirmação ou etapa obrigatória.

## Verificação local

[Evidência estruturada](evidence/fiscal-accounting-layout.json) registra checks, hashes das fontes e resultados locais. Nenhuma captura privada foi adicionada ao repositório. As capturas produzidas pelo roteiro usam apenas fixtures sintéticas e permanecem em `artifacts/browser-fiscal-sales-accounting/` (ignorado pelo Git).

- `node --test frontend/tests/*.test.js`: **202 aprovados**. Inclui três novos casos de subguias, contexto e cancelamento/resposta atrasada, além das regressões existentes.
- `npm --prefix frontend run build`: aprovado; aviso de chunk principal acima de 500 kB permanece (870,82 kB / 257,80 kB gzip).
- `python scripts/ci/versioning.py check --expected 0.9.0-dev.36`: aprovado. `git diff --check`: aprovado. O projeto não define comando de lint separado em `frontend/package.json`.
- Backend: **71 aprovados**, sem erros/falhas/skip, nos módulos `test_fiscal_sales_accounting`, `test_fiscal_incoming_accounting`, `test_direct_fiscal_accounting`, `test_fiscal_sales_composition`, `test_fiscal_accounting_prosoft_composition` e `test_workspace_context`. Inclui precisão em centavos, isolamento, planos configurados, permissões, competência fechada/reaberta, estornos, idempotência e composição Prosoft/SPED.
- `python scripts/browser_fiscal_sales_accounting.py`: **11 grupos aprovados**, Chromium 151.0.7922.34, zero erros JavaScript. Verifica ambos os menus, entradas/saídas, seleção/filtros/paginação, repetição de subguias e teclado Home/End/setas, contas/histórico preservados e zero leituras adicionais nas subguias. Testa prévia cancelada sob latência, solicitação cuja resposta se perde depois do commit, repetição idempotente, empresa sem modelos, competência F8 e isolamento entre três empresas.
- Inspeção visual de capturas sintéticas desktop e mobile: grade começa em y=632,28 no viewport desktop 1600×1100; controles e documento sem extravasamento em 390 px; tabela larga com rolagem contida. Configuração também verificada em 1100 px.

Reprodução backend: configurar um `ESCRITURA_DATA_DIR` descartável e `ESCRITURA_DEMO=0`, adicionar `tests:scripts:.` ao `PYTHONPATH` e executar `python -m unittest` com os seis módulos acima. O roteiro de navegador cria seu próprio diretório temporário e servidor local, com `ESCRITURA_DEMO=1`. Aceita `ESCRITURA_TEST_BROWSER` para um Chromium instalado. Neste executor foi necessário fornecer as dependências já declaradas pelo projeto em diretório isolado de testes; nenhuma dependência do produto foi alterada.

## Limites

Não foram executados localmente a suíte backend integral, PostgreSQL, instaladores/Qt, Windows/macOS, escala de produção ou certificação de acessibilidade. A CI do head publicado deve ser conferida separadamente. Importação automática e distribuição contábil por itens continuam pendentes. O Diário Consolidado permanece consulta independente. Esta alteração visual não modifica essas coberturas, não implementa relatórios/DF-e e não altera dados existentes. Sem merge, implantação ou publicação de release.
