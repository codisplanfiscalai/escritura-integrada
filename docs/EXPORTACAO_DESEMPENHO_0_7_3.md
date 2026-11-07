# Exportação, prévia e desempenho · 0.7.3

## Causas e correções

- `DesktopWindow.on_loaded(False)` tratava qualquer navegação interrompida como perda da interface. O Qt também emite esse sinal ao delegar downloads ou recusar navegação. Agora verifica se a área de trabalho continua presente e a conserva, inclusive após cancelar o salvamento. Falhas reais oferecem **Reabrir interface**, sem exigir reinício do motor.
- `show_window()` chamava `showNormal()`, retirando a maximização. Agora apenas restaura a janela minimizada, mostra e ativa a janela, conservando seu estado maximizado.
- Links de arquivos podiam substituir a aplicação por uma resposta de erro. O tratamento compartilhado valida a resposta antes de iniciar o download, exibe andamento/erro e impede pedidos simultâneos do mesmo arquivo. Os nomes originais, arquivos XML/JSON e PDFs continuam disponíveis.
- A impressão dos livros usava um `blob:` em uma janela que o desktop não admitia. Fiscal, Contábil, Financeiro e apurações usam agora URLs autenticadas de impressão, encaminhadas ao leitor PDF nativo. O Auditor conserva sua prévia. No navegador, o PDF abre separadamente. A prévia nativa permite maximizar, escolher página, ajustar zoom, salvar, imprimir e fechar por Esc.
- A prévia depende da ação **imprimir**, sem conceder automaticamente a ação **exportar**. As permissões e os filtros continuam validados no backend. Não foram criados relatórios de rotinas sociais ainda não especificadas.

## Leitura e interface

- A autenticação cotidiana não calcula a matriz inteira de permissões. Cada rota continua verificando no banco a empresa, a rotina e a ação. Não há cache de autorização; desativação ou revogação afeta a próxima requisição. A matriz completa continua disponível no cadastro/contexto/sessão.
- A consulta fiscal lê documentos em lote e, na listagem, suas origens em uma segunda consulta. O filtro anual é aplicado no SQL antes da desserialização. O relatório mantém o mesmo período, filtros, totais e vínculos de origem.
- Relatórios e documentos exibem até 50 registros por página. Os totais e as exportações incluem todos os registros filtrados. Os relatórios anteriormente criavam todas as linhas no DOM e apenas ocultavam as excedentes.
- Recursos da interface não repetem o carregamento na primeira ativação de uma guia. Reativação, mudança de empresa/exercício e alterações continuam atualizando os dados.

## Medição local reproduzível

Reproduzir a versão corrente: `python scripts/benchmark_fiscal.py`.

Ambiente Linux de desenvolvimento, SQLite temporário, usuário personalizado, 3.002 documentos sintéticos; mediana de três execuções, sem exportação PDF. Não é uma estimativa de tempo para todo equipamento ou base de produção.

| Operação | Antes | Depois | SQL antes → depois |
|---|---:|---:|---:|
| Relatório fiscal documental | 92,32 ms | 45,22 ms | 6.008 → 4 |
| Listagem documental completa | 79,93 ms | 39,51 ms | 6.006 → 5 |
| Sessão usada nas requisições | 4,51 ms | 1,34 ms* | 808 → 3 |

\* Leitura leve medida individualmente; a sessão completa para apresentação continua disponível. Comandos de abertura/fechamento de transação contam na medição SQL.

## Validação

- `tests/test_export_performance.py`: equivalência da listagem com o detalhe, origens, ordenação, isolamento entre empresas, filtro por ano, totais, limites de consultas SQL, desativação de usuário e impressão sem permissão de exportar.
- `frontend/tests/files.test.js`: erros 401/403/409/500, arquivo vazio, nomes de arquivo, acentos, PDF e originais JSON.
- `scripts/browser_exports.py`: PDF/Excel/prévia nos três módulos, resposta 403 seguida de nova exportação, preservação da aplicação e tabela de 5.000 registros com somente 50 linhas no DOM.
- `app/desktop_export_smoke.py`: download direto legado, exportações fiscais/contábeis, cancelamento financeiro e prévias dos três módulos. O executável verifica a área de trabalho, um marcador de contexto e a maximização depois de cada ação. O teste gráfico anterior do Auditor permanece.
- Windows e macOS executam esses fluxos no aplicativo empacotado antes da publicação. Os arquivos JSON e capturas são anexados aos artefatos de validação do workflow; a execução deve estar concluída com sucesso para considerar esses ambientes validados.

Não há alteração do esquema ou migração de dados nesta correção. A comparação com os dados reais do escritório depende de executar a nova versão nessa instalação; não foram acessados os bancos do usuário.
