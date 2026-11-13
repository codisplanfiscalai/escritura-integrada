# Documento cancelado conforme livro validado

A opção **Novo documento → Cancelado conforme livro validado** registra uma afirmação documental do livro já conferido. Não cancela uma nota na SEFAZ, não inventa XML/evento e não converte um documento existente. O operador informa fonte (arquivo/página/linha), responsável e motivo. Datas e classificação são atribuídas ao livro, sem alegação de emissão eletrônica verificada.

O registro mantém `status` de conferência/escrituração separado de `document_state=cancelled` e de `book_cancellation`. Sua origem é `validated_fiscal_book`. Valores escriturados são zerados; itens e tributos declarados ficam vazios. Bases e valores declarados permanecem não informados e não contam cobertura tributária; ele percorre conferir → escriturar, sem geração de partidas ou títulos. Não exige CFOP inventado quando o livro não o fornece. A linha entra no livro somente após escrituração, com valores zerados e proveniência visível em PDF/XLSX. O auditor separa o registro dos documentos economicamente ativos.

A inclusão é protegida por autorização, competência aberta, apuração não finalizada, identidade por empresa/direção/modelo/série/número (e emitente identificado nas entradas), repetição idempotente e transação SQLite. Identidade numérica ignora zeros à esquerda na checagem de colisão. Uma divergência com registro existente é bloqueada, nunca resolvida por alteração automática. A inclusão fica imutável, incluindo origem; sua escrituração pode ser revertida pelo fluxo auditado existente. Correção documental exige processo deliberado, não edição silenciosa. Não há migração de schema.

## Roteiro sintético

1. Em base temporária sem demo, criar saída modelo 55, série 1, número 90201, competência aberta, total zero, sem itens/tributos.
2. Ativar a opção de cancelamento pelo livro; indicar “Livro sintético, página 2, linha 3”, responsável e motivo.
3. Salvar, conferir e escriturar. Não deve existir integração contábil/financeira disponível.
4. Filtrar canceladas; abrir livro de saídas e exportar PDF/XLSX. Conferir linha zero, origem e ausência de validação eletrônica.
5. Repetir confirmação com mesma chave idempotente. Não deve duplicar.
6. Tentar editar, vincular título, registrar XML normal com mesma identidade, usar período fechado ou criar sem evidência. Cada ação deve ser bloqueada, sem efeitos parciais.
7. Fechar/reabrir inclusão e alternar tipo antes de salvar; nenhum cancelamento deve vazar ao próximo registro comum.

Testes automatizados: `tests/test_book_cancellation.py` e `frontend/tests/document-edit.test.js`, com dados exclusivamente sintéticos. O roteiro visual deve ser executado antes da homologação de interface.
