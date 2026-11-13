# Contexto e competência sugerida

F8 permite localizar a empresa por código literal, código numérico com zeros à esquerda, nome ou CNPJ. Códigos literais têm prioridade; equivalências ambíguas exigem escolha explícita. F9 remove empresa e preferências de ano/mês após confirmação do servidor, sem apagar movimentos. Edições, confirmações, operações pendentes e outras janelas bloqueiam os atalhos.

A competência fixada sugere filtros em Documentos, Diário, Conciliação, relatórios, Auditor, consulta CFOP e exportação contábil Prosoft. As rotinas mensais usam o mês operacional quando não há fixação; o Diário e os relatórios anuais continuam com todo o exercício. A apuração usa o mesmo helper em sua integração própria.

O usuário pode editar ou limpar cada filtro. Essa escolha é preservada ao navegar, atualizar dados ou trocar a preferência. Trocar empresa ou exercício reinicializa a sugestão. Sem empresa os filtros sugeridos ficam vazios. Nenhuma sugestão altera o mês operacional, datas de documentos ou regras fiscais. Os mapeamentos Prosoft persistem ao trocar de módulo; prévias e respostas antigas são invalidadas quando o contexto ou competência muda.

A roda sobre tabelas pode alcançar a rolagem vertical da página; a barra lateral mantém rolagem por teclado, barra fina e modo de alto contraste. A largura do menu não muda.

Validação automatizada: suíte frontend e build de produção. Testes unitários não substituem aceite visual em navegador real.

O cenário `scripts/browser_workspace_context.py` prepara uma empresa sintética e cobre busca/F8, F9, mês manual preservado, bloqueio durante edição e rolagem. No ambiente local de reconstrução, Chromium não chegou a abrir: `socket() failed: Operation not permitted` (AF_UNIX). O cenário deve ser executado no CI; não há aceite visual local declarado.
