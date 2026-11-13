# Operações individuais e em lote

Disponíveis nas tabelas de documentos fiscais e lançamentos contábeis. Uma seleção de um registro usa as mesmas verificações de um lote.

## Operação simples

1. Ative a empresa e o módulo. Use **Operar selecionados** para até 5.000 registros de uma competência ou **Limpar tudo neste módulo** para todos os movimentos da empresa, de **todos os exercícios**, independentemente dos filtros, da página ou da seleção. Cadastros e outras empresas não são apagados.
2. A prévia abre automaticamente. Confira quantidades, competências, dependências e evidências conservadas. Na limpeza completa, os movimentos protegidos são separados e permanecem identificados com seus motivos. A seleção manual continua bloqueada integralmente se algum registro não puder ser processado.
3. Clique uma vez em **Excluir definitivamente N registros**. Não é necessário digitar frases, preencher justificativa ou marcar uma segunda confirmação. A observação é opcional. Incluir contabilidade vinculada e pares de estorno continua sendo uma escolha explícita na prévia.
4. Uma única transação revalida acesso, estado, dependências e períodos de todos os movimentos elegíveis. Não há sucesso parcial desse conjunto. Se algo mudou, a prévia deve ser renovada. Ela expira em 15 minutos e pertence à mesma sessão que a gerou.

Na limpeza completa, um período fechado ou vínculo protegido não impede a exclusão de registros independentes elegíveis. Componentes vinculados não são desmembrados de forma a deixar referências inválidas. Uma dependência contábil bloqueada preserva os documentos do mesmo componente contábil; os componentes independentes continuam elegíveis. Não há reabertura automática ou cascata financeira.

## Consulta e Excel

As tabelas fiscal e contábil oferecem páginas de 50, 100, 250, 500, 1.000, 2.500 e 5.000 registros. Selecionar visíveis não seleciona outras páginas. Alterar filtros, página, empresa ou exercício limpa a seleção.

**Exportar Excel** gera um XLSX com o resultado completo dos filtros atuais no exercício consultado, não apenas a página ou os checkboxes selecionados. Exige permissão de consulta e exportação da rotina. O servidor reaplica os filtros e o contexto da empresa; textos são gravados como texto, sem execução de fórmulas de planilha.

## Exclusão física

A rotina executa `DELETE` nas linhas de documentos ou lançamentos e em seus filhos exclusivos (`document_sources` ou `journal_lines`). Não troca o estado para cancelado, oculto ou excluído lógico. O estado pendente, conferido, escriturado ou estornado não é, sozinho, motivo para impedir a exclusão.

Competências fechadas e exercícios não habilitados protegem os movimentos correspondentes: bloqueiam a seleção manual ou os preservam na limpeza completa. Documentos fiscais também exigem que as apurações finalizadas tenham sido revertidas previamente, respeitando a sequência de dependências. A rotina não reabre competências nem desfaz encerramentos automaticamente. A situação fiscal não bloqueia um lançamento contábil independente quando o período contábil está aberto.

Um documento com contabilidade vinculada exige a opção explícita de incluir os lançamentos na prévia, permissão contábil adicional e a seleção completa dos documentos que compartilham aquela contabilização. A opção de incluir pares de estorno expande somente a cadeia contábil vinculada; todas as competências/exercícios atingidos, inclusive em outro ano, devem estar habilitados e abertos. A prévia apresenta esses períodos e a confirmação identifica o conjunto ampliado. A seleção manual admite até 5.000 registros; a limpeza completa não exige dividir o conjunto em lotes de 500.

Títulos financeiros, baixas, ajustes fiscais e outras referências não autorizadas protegem os movimentos envolvidos, com indicação concreta da dependência. Não há cascata financeira implícita, mesmo quando um título está cancelado ou uma baixa foi estornada. Resolva a dependência por seu fluxo próprio antes de preparar outra prévia.

## O que permanece

Originais de importação, arquivos compartilhados e materializados, cenários/memórias de apuração, snapshots do Auditor, exportações anteriores, trilha de auditoria e backups são preservados como evidências históricas. A exclusão de movimentos não promete apagar todas as cópias dessas informações nem sobrescrever fisicamente discos ou o WAL do SQLite. As contagens e os avisos aparecem antes da confirmação.

Há um registro mínimo dos IDs/chaves excluídos para impedir sua reutilização e evitar que uma referência histórica aponte para outro movimento. Esse registro não conserva o movimento completo nem permite restaurá-lo. Resultados de importações/operações afetados ficam impedidos de repetir os IDs antigos; um pedido antigo retorna conflito `movement_deleted`, em vez de recriar dados silenciosamente. A exclusão não tem função de desfazer: uma eventual recuperação exige uma cópia adequada e um procedimento separado.

## Conferência, escrituração e alterações

- **Conferir fiscal:** documentos pendentes e importações já escrituradas que ainda aguardam revisão. Registra a observação opcional ou o motivo operacional padrão e mantém a contabilidade vinculada.
- **Escriturar fiscal:** exige conferência anterior. Não cria partidas contábeis, títulos, parcelas ou outros efeitos implícitos.
- **Alterar CFOP:** somente documentos não escriturados, sem itens nem registros analíticos. Valida a classificação e invalida a conferência anterior. Documentos mais complexos exigem edição detalhada para manter cabeçalho e itens coerentes.
- **Alterar contábil:** apenas histórico e identificação documental, com limites de texto. Valores, contas, partidas, datas e identidade dos lançamentos não são alterados em lote.

As alterações/conferências geram eventos individuais com os campos modificados, motivo e versão anterior quando aplicável, além do evento agregado. A exclusão conserva uma trilha mínima do conjunto, sem copiar o conteúdo completo apagado.

## API e segurança

Rotas sob `/api/companies/{cid}/bulk-operations`:

- `POST /preview`: `kind` (`documents` ou `journals`), `action` (`delete`, `review`, `book`, `update`), `period`, `scope` (`selection` ou `company`), `ids`, `changes`, `include_linked_journals` e `include_reversal_pairs` quando aplicáveis.
- `POST /confirm`: `preview_id`, `preview_hash`, `irreversible_acknowledged: true` para exclusão. `reason` é opcional; não há frase obrigatória. O clique de confirmação da interface envia esse reconhecimento. A confirmação não pode substituir a seleção ou os campos da prévia.

São exigidos sessão autenticada, CSRF, empresa/módulo/exercício corretos, consulta da rotina e a ação específica. Excluir exige `fiscal.documents.delete` ou `accounting.journals.delete`; incluir contabilidade exige também consulta/exclusão contábil. Conferência/alteração exige edição e escrituração exige a permissão própria de escriturar. Os direitos são conferidos novamente dentro da transação, inclusive após uma revogação.

Essa capacidade operacional não certifica o cumprimento de prazos legais de guarda ou autoriza a exclusão de dados reais pelo assistente. Cabe ao responsável decidir a adequação da exclusão e conservar as cópias necessárias.
