# Parâmetros operacionais por empresa

Em **Sistema → Empresas**, abra a empresa desejada e a aba **Operação**. As restrições operacionais começam **desativadas**, inclusive para empresas existentes sem configuração salva. Nenhum movimento é excluído nem reimportado por essa migração.

## Opções

- Pedir confirmações adicionais: desativado por padrão. Importação e limpeza usam a prévia e um único botão final com o efeito explícito. Quando ativado, um modal extra é mostrado.
- Exigir conferência em etapa separada: desativado por padrão. **Conferir e escriturar** registra as duas etapas em uma transação, sem precisar marcar como conferido antes. Exige as permissões de conferência e escrituração; qualquer falha reverte as duas etapas.

- Respeitar bloqueios mensais: quando desativado, o mês pode continuar marcado como fechado, mas a marcação não impede alterações. Não reabre meses automaticamente.
- Exigir prazo de retenção em limpezas manuais.
- Proteger originais de documentos importados.
- Bloquear importações, exclusões de movimentos ou limpeza de lotes, independentemente.
- Limitar tamanho por arquivo e quantidade de registros selecionados. Os valores só atuam quando a respectiva opção estiver ativada.

A limpeza programada continua desativada por padrão. Se ativada explicitamente, sempre respeita o prazo configurado, mesmo quando a retenção manual estiver desativada. Uma empresa bloqueada não interrompe a programação das demais. O limite opcional de seleção distribui o trabalho entre execuções.

**Salvar configuração como modelo** captura os parâmetros já salvos. Modelos podem ser aplicados nas outras empresas acessíveis ao mesmo usuário. O modelo padrão **Sem restrições operacionais** sempre está disponível. Aplicar um modelo salva somente a empresa de destino. A configuração usa versão para não sobrescrever alterações concorrentes e gera trilha de auditoria.

A leitura exige acesso à empresa. Gravação e criação/aplicação de modelos exigem administrador com permissão de edição. Modelo de empresa inacessível não é exposto.

## Fluxo simplificado

A consulta de documentos começa na competência ativa. Marcar um documento como conferido não pede uma observação obrigatória por padrão. Na escrituração, a observação é opcional; o usuário continua escolhendo explicitamente contabilização e geração de títulos, sem inferir contas, parcelas ou datas. A escrituração mantém as datas do documento e sua identidade.

Prévia de importação já salva pode ser deixada sem pergunta adicional quando não houve revisão manual. Alterações de revisão ainda não salvas continuam protegidas. Avisos informativos sobre validações não realizadas ficam separados de impedimentos. A limpeza de pacotes conserva os movimentos em todos os modos. Ativar uma programação futura de remoção de originais continua exigindo ciência explícita do efeito.

## Gerar cobrança de notas já escrituradas

No histórico de um lote confirmado, **Gerar cobranças XML** prepara somente as duplicatas explícitas das notas de compra já existentes. A prévia mostra quantidade de notas, parcelas e soma dos valores. CFOPs, datas, totais vNF, decisões de revisão, versões e demais colunas dos documentos fiscais não são regravados nesse modo. Não há pagamento nem baixa.

A operação usa o identificador do documento e o número da duplicata para criar vínculos. Repetição preserva os títulos já gerados; divergência de valores, vencimentos, baixas ou outros efeitos bloqueia a recriação. Cópias idênticas do XML no mesmo ZIP são consolidadas por documento. Notas sem cobrança explícita não recebem parcelas inventadas. A cobrança legada pode ser recuperada do original exato, sem refazer a importação fiscal.

No reprocessamento fiscal comum, CFOPs e decisão de total vNF existentes são mantidos até que o usuário solicite uma substituição explícita.

## Reenviar um original removido

Envie o mesmo arquivo em **Importações fiscais**. O SHA-256 e o tamanho são conferidos, os bytes são recuperados no lote existente e as marcações de arquivo removido são baixadas na mesma transação. O nome pode ser diferente; os bytes precisam ser idênticos.

- Lote, confirmação, documentos, lançamentos, títulos, dados normalizados e vínculos permanecem intactos.
- Histórico ocultado continua ocultado até o usuário restaurá-lo.
- Reenvio repetido não duplica o lote nem movimentos.
- Restaurar o original não recria movimentos que tenham sido excluídos separadamente e não desfaz revisões manuais.

**Limpar lote** remove/oculta o pacote conforme o modo escolhido. **Excluir movimentos** é outra operação, com prévia e confirmação explícita. Limpar lotes jamais exclui lançamentos.

## Proteções técnicas e de integridade

Não são restrições operacionais e não podem ser desativadas: autenticação, empresa/exercício do contexto, permissões, consistência contábil, vínculos referenciais, duplicidade/idempotência, apurações finalizadas, hash e revisão da prévia, confirmação irreversível e proteção de arquivos compartilhados com outros módulos.

A importação fiscal/contábil/financeira admite até **128 MiB por envio** como proteção técnica. Compactados continuam limitados a 20 MiB por membro, 80 MiB expandidos, 1.000 membros, profundidade 2 e proporção de expansão 200. O intercâmbio de planos conserva o teto técnico de 15 MB e também respeita o bloqueio operacional e limites menores. Limites de parser/XML/CSV e de anexos/catálogos do Auditor permanecem explícitos para evitar consumo excessivo de memória e conteúdo inválido. Ativar o limite operacional permite escolher um limite menor, por empresa.

## Verificação

Testes sintéticos cobrem padrões livres, isolamento, autorização, versão concorrente, modelos, bloqueio mensal opt-in, limites, revalidação no momento de confirmar, restauração por hash, original corrompido, limpeza sem mudança nos movimentos e programação independente por empresa. As suítes legadas de fechamento ativam explicitamente a política mensal restritiva em suas fixtures.
