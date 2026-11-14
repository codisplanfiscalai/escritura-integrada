# Gerenciador de planos de contas

## Recursos disponíveis

- Em **Contábil → Gerenciar planos globais**, administradores podem criar um
  plano vazio ou abrir uma edição a partir de uma versão global existente.
- Contas e subcontas podem ser incluídas, editadas e removidas do rascunho, com
  acesso textual independente do classificador, natureza, tipo sintético ou
  analítico, situação, grupo de demonstrativo e exigência de centro de custo.
- Máscara e grupos podem ser editados. Metadados de origem e campos Prosoft
  desconhecidos permanecem preservados quando uma conta existente é editada.
- A pesquisa e a paginação não limitam a quantidade de contas salvas. O servidor
  aceita até 50.000 contas no plano. Prefixos sem conta-pai explícita são avisos,
  sem geração automática de códigos ou contas.
- O fluxo final é **Editar → Salvar plano na biblioteca**. Os rascunhos podem
  ser retomados. Não há motivo ou checkbox adicional obrigatório.

## Uso por empresa e preservação dos movimentos

A configuração em **Empresas → Editar → Contábil** permite adotar a definição
global sem cópia ou duplicá-la para plano próprio (integral ou usadas/pais).
O plano operacional próprio continua na rotina existente **Plano de contas**,
com inclusão/edição de contas sintéticas e analíticas e atalho **Subconta**.

Salvar a edição global cria uma nova versão imutável: não altera silenciosamente
contas ou lançamentos de nenhuma empresa. O gerenciador identifica as empresas
que permanecem na versão anterior, incluindo o modo de vínculo e linhas
contábeis relacionadas. Para adotar a nova versão é necessário abrir os
parâmetros da empresa e analisar a prévia de impacto dos serviços existentes.
Os identificadores operacionais e movimentos anteriores são preservados;
conflitos de estrutura usada não são resolvidos por remapeamento silencioso.

A nova versão referencia a origem. Os bytes e a definição anteriores continuam
existindo, inclusive quando uma conta foi removida do rascunho novo. A mesma
operação de salvar repetida devolve a versão já criada, sem duplicar o plano.

## Segurança e persistência

Rascunhos globais são administrativos. Acesso, sessão e CSRF são revalidados no
servidor; revisão concorrente é recusada antes da gravação. Salvar definição,
lote nativo, entradas, marcador e auditoria é uma única transação. Os rascunhos
usam a tabela `meta` existente; não há migração de esquema nem dependência do
Atlas. A biblioteca continua nos serviços/tabelas globais existentes.

## Limites

- É preciso selecionar uma empresa como contexto administrativo de origem;
  isso não torna o plano global uma cópia privada dessa empresa.
- Cada empresa continua com um único plano operacional corrente. Não há nesta
  etapa biblioteca de múltiplos planos privados inativos por empresa.
- O gerenciador não renumera ou migra automaticamente partidas entre versões.
- Não declara que um classificador ou natureza escolhido está contabilmente
  correto nem homologa arquivos na Prosoft, ECD ou ECF.
- Exclusão é do rascunho; versões globais já usadas não são apagadas por aqui.
- Rascunhos ainda não possuem expurgo ou exclusão global próprios.
- A máscara interna não garante, sozinha, compatibilidade com o limite e as
  flags do layout Prosoft; os controles do exportador continuam necessários.

## Verificação local

Testes backend verificam criação manual, versões, metadados, uso em empresas,
lançamentos preservados, CSRF, isolamento administrativo, CAS, rollback,
repetição e acesso textual com barra. Testes frontend cobrem o fluxo de salvar,
identidade textual, contexto, rascunhos e atalho de subconta. Build aprovado.

PostgreSQL real, navegador visual, binários e homologação na Prosoft ainda não
foram executados nesta entrega. Nenhum push, merge, release ou deploy foi feito.
