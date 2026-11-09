# Operações individuais e em lote

Disponíveis nas tabelas de documentos fiscais e lançamentos contábeis. Uma seleção de um registro usa as mesmas verificações de um lote. Não existe comando implícito para apagar todos os dados da empresa.

## Operação

1. Ative a empresa, módulo e exercício. Selecione os registros pelos checkboxes. Na tabela fiscal, o tamanho da página pode ser 50, 100, 250 ou 500; selecionar visíveis não seleciona outras páginas. Alterar filtros, página, empresa ou exercício limpa a seleção.
2. Abra **Operar selecionados** e escolha uma operação permitida. A seleção original deve pertencer a uma única competência e conter de 1 a 500 IDs distintos.
3. Gere a prévia. Confira empresa, competência, registros, dependências, competências adicionais, quantidades afetadas e evidências que serão conservadas. Bloqueios impedem a confirmação do conjunto inteiro.
4. Informe a justificativa. Para excluir, reconheça a irreversibilidade e digite integralmente a frase apresentada, que identifica a empresa, a quantidade e o período/conjunto. A prévia expira após 15 minutos e pertence à mesma sessão que a gerou.
5. Confirme. A transação revalida acesso, estado, dependências e períodos antes de concluir. Não há sucesso parcial do lote. Se a origem mudou, gere uma nova prévia.

## Exclusão física

A rotina executa `DELETE` nas linhas de documentos ou lançamentos e em seus filhos exclusivos (`document_sources` ou `journal_lines`). Não troca o estado para cancelado, oculto ou excluído lógico. O estado pendente, conferido, escriturado ou estornado não é, sozinho, motivo para impedir a exclusão.

Competências fechadas e exercícios não habilitados bloqueiam a operação. Documentos fiscais também exigem que as apurações finalizadas tenham sido revertidas previamente, respeitando a sequência de dependências. A rotina não reabre competências nem desfaz encerramentos automaticamente. A situação fiscal não bloqueia um lançamento contábil independente quando o período contábil está aberto.

Um documento com contabilidade vinculada exige a opção explícita de incluir os lançamentos na prévia, permissão contábil adicional e a seleção completa dos documentos que compartilham aquela contabilização. A opção de incluir pares de estorno expande somente a cadeia contábil vinculada; todas as competências/exercícios atingidos, inclusive em outro ano, devem estar habilitados e abertos. A prévia apresenta esses períodos e a confirmação identifica o conjunto ampliado. O limite de 500 lançamentos efetivos permanece aplicado.

Títulos financeiros, baixas, ajustes fiscais e outras referências não autorizadas impedem a exclusão com uma indicação concreta da dependência. Não há cascata financeira implícita, mesmo quando um título está cancelado ou uma baixa foi estornada. Resolva a dependência por seu fluxo próprio antes de preparar outra prévia.

## O que permanece

Originais de importação, arquivos compartilhados e materializados, cenários/memórias de apuração, snapshots do Auditor, exportações anteriores, trilha de auditoria e backups são preservados como evidências históricas. A exclusão de movimentos não promete apagar todas as cópias dessas informações nem sobrescrever fisicamente discos ou o WAL do SQLite. As contagens e os avisos aparecem antes da confirmação.

Há um registro mínimo dos IDs/chaves excluídos para impedir sua reutilização e evitar que uma referência histórica aponte para outro movimento. Esse registro não conserva o movimento completo nem permite restaurá-lo. Resultados de importações/operações afetados ficam impedidos de repetir os IDs antigos; um pedido antigo retorna conflito `movement_deleted`, em vez de recriar dados silenciosamente. A exclusão não tem função de desfazer: uma eventual recuperação exige uma cópia adequada e um procedimento separado.

## Conferência, escrituração e alterações

- **Conferir fiscal:** documentos pendentes e importações já escrituradas que ainda aguardam revisão. Registra a justificativa e mantém a contabilidade vinculada.
- **Escriturar fiscal:** exige conferência anterior. Não cria partidas contábeis, títulos, parcelas ou outros efeitos implícitos.
- **Alterar CFOP:** somente documentos não escriturados, sem itens nem registros analíticos. Valida a classificação e invalida a conferência anterior. Documentos mais complexos exigem edição detalhada para manter cabeçalho e itens coerentes.
- **Alterar contábil:** apenas histórico e identificação documental, com limites de texto. Valores, contas, partidas, datas e identidade dos lançamentos não são alterados em lote.

As alterações/conferências geram eventos individuais com os campos modificados, motivo e versão anterior quando aplicável, além do evento agregado. A exclusão conserva uma trilha mínima do conjunto, sem copiar o conteúdo completo apagado.

## API e segurança

Rotas sob `/api/companies/{cid}/bulk-operations`:

- `POST /preview`: `kind` (`documents` ou `journals`), `action` (`delete`, `review`, `book`, `update`), `period`, `ids`, `changes`, `include_linked_journals` e `include_reversal_pairs` quando aplicáveis.
- `POST /confirm`: `preview_id`, `preview_hash`, `reason`, `confirmation_phrase` e `irreversible_acknowledged` para exclusão. A confirmação não pode substituir a seleção ou os campos da prévia.

São exigidos sessão autenticada, CSRF, empresa/módulo/exercício corretos, consulta da rotina e a ação específica. Excluir exige `fiscal.documents.delete` ou `accounting.journals.delete`; incluir contabilidade exige também consulta/exclusão contábil. Conferência/alteração exige edição e escrituração exige a permissão própria de escriturar. Os direitos são conferidos novamente dentro da transação, inclusive após uma revogação.

Essa capacidade operacional não certifica o cumprimento de prazos legais de guarda ou autoriza a exclusão de dados reais pelo assistente. Cabe ao responsável decidir a adequação da exclusão e conservar as cópias necessárias.
