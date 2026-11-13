# Plano de contas: modelo e intercâmbio

## Finalidade e limites

O arquivo `app/data/account-plan-default.json` é um modelo independente, editável e importável no formato nativo `escritura-account-plan/v1`. Contém 73 contas genéricas, sintéticas e analíticas, sem dados de empresas ou pessoas. Não foi extraído do TXT privado usado como referência de interoperabilidade.

O modelo é um ponto de partida operacional. Não certifica um plano legal obrigatório, conformidade com normas contábeis, enquadramento tributário, classificação fiscal ou adequação a um setor. O responsável contábil deve revisar contas, natureza, grupos de relatório e propriedades antes de utilizá-lo. Não inclui todas as contas redutoras, deduções, provisões ou particularidades que uma empresa pode precisar.

## Estrutura do formato nativo

O JSON possui `schema`, `properties` e `accounts`. As propriedades padrão são:

- `mask`: `#.#.##.###`;
- `generated_access`: `0`;
- `groups`: ativo `1`, passivo `2`, compensação `9`, custos `4`, despesas `5`, receitas `3`;
- `plan_type`: `0`;
- `special_mask`: vazio.

A propriedade do grupo de compensação não cria contas de compensação automaticamente. O modelo não inclui esse grupo, que requer revisão do uso e dos relatórios antes de ser acrescentado.

Cada conta possui `access_code`, `classifier`, `name`, `nature` (`debit` ou `credit`), `analytical`, `requires_cost_center`, `active`, `report_group`, `prosoft_code` e `prosoft`. Os acessos são strings numéricas entre `10000` e `10072`, distintos dos acessos `1` a `6` das contas iniciais. O código Prosoft inicial é igual ao acesso do modelo; isso não confirma a existência da conta em outra instalação.

Os classificadores sintéticos usam prefixos completos da máscara: `1`, `1.1` e `1.1.01`; as contas analíticas ocupam o quarto nível, como `1.1.01.001`. Os nomes do modelo têm até 30 caracteres ASCII, escritos sem acentos, para dispensar transliteração ou truncamento na saída Prosoft. Novas contas não devem ser truncadas silenciosamente para caber no destino.

Em `prosoft`, `entries` é `0` nas sintéticas e `1` nas analíticas. `monetary_correction`, `reducer`, `cost_center`, `currency_conversion` e `reconciliation` são `0`; `special_classifier` e `special_name` são vazios. Todas as contas estão ativas e não exigem centro de custo.

O `report_group` pertence ao modelo de relatórios do Escritura, não ao layout Prosoft: `asset`, `liability`, `equity`, `revenue` ou `expense`. Custos e despesas usam `expense`; patrimônio líquido usa `equity`, embora seus classificadores estejam sob o grupo `2`. Não se deve inferir a natureza ou o grupo de relatório apenas de um acesso numérico.

## Aplicação e preservação das contas existentes

A aplicação do modelo deve passar por prévia e confirmação, mantendo a empresa selecionada e permitindo revisar inclusões, conflitos e avisos. A correspondência por classificador preserva as contas já existentes, seus identificadores e sua relação com lançamentos. Aplicar o modelo não deve substituir os acessos antigos pelos acessos do arquivo nem sobrescrever a política contábil da empresa.

Foram conservados os seis classificadores iniciais:

| Classificador | Nome do modelo |
| --- | --- |
| `1.1.01.001` | Caixa |
| `1.1.02.001` | Bancos conta movimento |
| `1.1.03.001` | Clientes |
| `2.1.01.001` | Fornecedores |
| `3.1.01.001` | Receitas operacionais |
| `4.1.01.001` | Despesas operacionais |

Existe uma diferença histórica importante: o cadastro inicial usa `4` para despesas, enquanto as propriedades do modelo destinam `4` a custos e `5` a despesas. Para compatibilidade, o modelo mantém `4.1.01.001` e chama o grupo superior de “Custos e despesas”. Isso não converte automaticamente despesas antigas em custos nem altera uma política já existente. Contas de ambos os grupos têm `report_group=expense`; a revisão da classificação detalhada cabe ao responsável contábil. A preservação por classificador também significa que o plano aplicado pode não ser uma cópia literal do JSON.

## Fluxo de importação e exportação

As rotinas de intercâmbio usam duas etapas: preparar a prévia e confirmar a operação revisada. As operações da API são `account-plans/preview`, `account-plans/{id}/confirm`, `account-plans/export-preview` e `account-plans/export-confirm`, sob o prefixo de API da aplicação. Consulte as rotas e os contratos efetivamente implementados para os campos de requisição e resposta.

1. Selecione a empresa e o formato de origem ou destino.
2. Prepare a prévia, sem tratar a leitura do arquivo como autorização para alterar o cadastro.
3. Revise propriedades, máscara, códigos, hierarquia, coincidências, conflitos, avisos e valores não reconhecidos.
4. Confirme somente a operação revisada. Se o conteúdo ou as opções mudarem, gere outra prévia.
5. Para exportar ao Prosoft, revise os bloqueios antes de gerar o arquivo e homologue a carga em uma instalação de teste do destino.

O JSON nativo preserva propriedades e metadados contábeis que o TXT Prosoft não representa integralmente. É o formato preferível para transportar o plano entre instalações do Escritura e guardar uma cópia editável. Uma exportação nativa não é um backup completo da empresa: não substitui o backup de lançamentos, saldos, documentos e demais cadastros.

## Biblioteca global operacional e identidade por acesso

O plano fornecido pelo escritório pode ser importado e publicado pelo administrador na **Biblioteca global de planos**. O nome do cadastro é livre: “050” identifica a origem Prosoft, não um registro SPED nem o modelo genérico de 73 contas. O TXT privado não integra o código-fonte, instaladores ou seeds. A publicação é uma ação explícita, com revisão de propriedades e autorização para que o conteúdo integral fique disponível às empresas desta instalação.

As versões globais são imutáveis. Cada empresa pode **usar a versão compartilhada**, protegida contra edição local, ou **duplicar para plano próprio**, adaptável e independente. A biblioteca aceita múltiplos planos globais e versões. Para o plano próprio há duas opções explícitas: **Duplicar integralmente** (padrão) ou **Somente contas usadas e pais existentes necessários**. Duplicar um vínculo compartilhado conserva os mesmos IDs e todos os lançamentos. Alterações próprias não mudam a versão global nem outras empresas. Publicar outra versão ou adotá-la exige nova ação explícita; não há sincronização retroativa automática.

Os acessos identificam contas distintas. O classificador é um agrupador hierárquico e pode se repetir: subcontas analíticas com acessos diferentes não devem ser mescladas, descartadas ou receber classificadores inventados. A migração de schema 6 remove apenas a unicidade do classificador, mantendo IDs, acessos, campos, índices adicionais, triggers e FKs compostas por empresa. Acesso continua único por empresa. A migração faz backup pré-upgrade, transação e conferência integral de chaves estrangeiras, revertendo em caso de erro.

A definição é compartilhada fisicamente, não duplicada por empresa. A adoção compartilhada grava somente o vínculo à versão: não copia contas, propriedades, metadados, JSON do plano ou bytes originais para a empresa. `global_account_entries` guarda as entradas uma única vez por versão; `effective_accounts` resolve a consulta combinando os cadastros locais com as entradas da versão vinculada. Nenhuma conta ou lançamento existente é removido ou substituído. Contas locais adicionais são preservadas e informadas na prévia. Acessos com características diferentes ou propriedades incompatíveis bloqueiam a operação inteira. No modo compartilhado, todas as contas da empresa ficam protegidas até a duplicação para adaptação. A cópia integral de atributos, propriedades, metadados e original ocorre somente ao escolher a duplicação própria integral. Na opção usada, entram contas efetivamente referenciadas por partidas/modelos ou por aliases de uso preservados, mais contas sintéticas da origem que representam seus classificadores ancestrais. Contas analíticas irmãs sem uso não são copiadas, mesmo com o mesmo classificador. Pais inexistentes são informados, nunca inventados. O lote próprio parcial guarda apenas o subconjunto em JSON nativo com referência à versão/hash global, não outra cópia integral do original. Sem contas usadas, a opção parcial copia zero contas globais e comunica isso explicitamente; os cadastros locais anteriores continuam preservados.

Contas globais ainda não utilizadas são apresentadas pela API como aliases negativos estáveis da entrada global, sempre sob o vínculo da empresa. O primeiro uso em partida ou modelo contábil cria apenas o ID operacional empresarial, o acesso e a referência à entrada, mantendo os atributos locais nulos. As partidas e modelos persistem IDs positivos com as FKs compostas originais. Aliases efetivamente usados são persistidos em `company_account_aliases` e continuam resolvendo a mesma referência empresarial, inclusive entre versões A→B→C, após duplicação própria ou renomeação/reutilização do acesso. Mapeamentos criados só para a cópia são marcados sem uso, para não transformar automaticamente todas as contas copiadas em contas utilizadas numa futura seleção parcial. Um alias de versão não vinculada não cria nem seleciona outra conta. Leituras, relatórios, exportações e prévias CSV não materializam contas. Período fechado, desequilíbrio ou falha de centro de custo reverte também qualquer referência criada na tentativa.

A biblioteca possui consulta paginada, pesquisa, prévia por hash e confirmação idempotente. Seletores de contas nas partidas, baixas, documentos, modelos e relatórios pesquisam a lista inteira, renderizando no máximo 200 correspondências mais a seleção atual. O plano e os mapeamentos Prosoft também são paginados. Um teste sintético cobre 22.596 contas; isso não constitui medição/homologação de desempenho do arquivo real em navegador nativo. Não aceita publicação com acesso duplicado. Flags desconhecidas são preservadas, mas a publicação não certifica seus significados nem remove os bloqueios de exportação Prosoft. A natureza de uma conta e a máscara precisam estar explicitamente resolvidas antes de publicar. O modo **Identificar contas por acesso** também permite importação tradicional de planos próprios com classificadores repetidos, sem exigir publicação global.

Rotas sob `/api/companies/{cid}/global-account-plans`:

- `GET /`: versões e vínculo da empresa; `GET /{id}?search=&page=1`: 100 contas por página.
- `POST /batches/{batch_id}/publish`: `name`, `description`, `preview_hash`, `reason`, `properties_reviewed=true`, `global_visibility_reviewed=true`, e `parent_id` opcional. Publicação somente para administrador.
- `POST /{id}/preview`: `mode=shared|own` e `copy_scope=all|used` para o próprio; retorna contagens, conflitos, ID e hash da prévia.
- `POST /previews/{id}/confirm`: `preview_hash`, `properties_reviewed=true`, `reason`. Exige autorização para adotar o plano, contexto ativo e CSRF. No modo compartilhado retorna `created=0`, `available` com o total da versão e `batch_id=null`. Alocação técnica no primeiro lançamento não exige permissão de criar cadastros, mas não permite editar a definição global ou local.
- `POST /binding/detach`: `version` do vínculo, `reason` e `copy_scope=all|used` (padrão `all`). Exige edição de contas e preserva IDs.

Originais e JSON nativo globais são baixados diretamente da versão, sem criar lote na empresa, em `GET /{id}/original` e `GET /{id}/native`, com a permissão usual de exportação. O plano próprio mantém também seu lote de cópia explícita. A exportação do plano efetivo resolve metadados e propriedades globais sem perda das flags originais. Mapeamentos CTBLCTOS aceitam o alias global e o ID empresarial correspondente, recusando configurações divergentes entre os dois. O backup integral verifica os hashes de `account_plan_batches` e `global_account_plans`, além dos demais originais. Backups anteriores continuam restauráveis, respeitando sua cobertura original e verificando também os hashes de planos presentes antes da promoção.

## Carga de referência e revisão do arquivo fornecido

O arquivo fornecido contém 22.596 acessos distintos, mas 428 classificadores distintos. Não é seguro descartar 22.168 linhas nem inventar classificadores para ativá-las. A biblioteca global e a identidade por acesso preservam essas contas distintas. O modo tradicional de importação, mantido por compatibilidade, continua fazendo correspondência também por classificador e bloqueia repetições até o usuário selecionar explicitamente a identidade por acesso.

A opção **Guardar como referência sem ativar contas** confirma a conservação de todas as linhas, metadados e bytes originais, sem torná-las disponíveis nos lançamentos. O histórico oferece o original e o JSON nativo completo em `account-plans/{id}/original` e `account-plans/{id}/native`. Para ativar contas, os conflitos precisam ser resolvidos em um arquivo revisado pelo responsável. O intercâmbio não substitui contas existentes e não altera contas usadas em lançamentos.

Uma linha da origem possui redutora fora do layout. Sua natureza só pode ser informada por decisão explícita em `options.nature_overrides`, pelo acesso da conta. Grupos sem natureza inequívoca exigem `properties.group_natures`. A interface oferece os ajustes JSON opcionais e exemplos ilustrativos, nunca aplicados automaticamente. O valor original permanece nos metadados e segue bloqueando uma saída Prosoft inválida.

A prévia e a interface exibem no máximo 100 contas, conflitos e avisos, com contagens totais. O processamento, a referência confirmada e o download nativo consideram todas as linhas. O limite por arquivo é 15 MB e o limite de contas é 50.000.

## Prosoft: layouts distintos

O TXT de **exportação do plano** possui registros de contas de 204 posições. Já o layout de **importação** documentado no PDF possui registro de propriedades `P` de 103 posições e registros de conta `C` de 204 posições. A coincidência do comprimento de uma conta não torna os formatos intercambiáveis. Não basta acrescentar uma letra a cada linha ou enviar o export original diretamente ao importador.

O arquivo real de referência foi descrito como contendo 22.596 linhas de 204 posições, codificadas em Windows-1252 (`cp1252`), com acentos e valores de flags não previstos no PDF. Esses dados são uma observação do arquivo informado, não uma certificação de compatibilidade com todas as versões do Prosoft. O arquivo privado não acompanha este repositório, nem deve ser usado como fixture pública.

A saída de exportação original não fornece a máscara e todas as propriedades necessárias para montar o registro `P`. A importação deve, portanto, exigir revisão explícita dessas propriedades. Uma máscara inferida da aparência das contas é uma proposta para revisão, não um dado recuperado do arquivo. Também é necessário explicitar a política para grupos finais preenchidos com zeros à direita: preservar o código textual não equivale a normalizá-lo como inteiro. Essa escolha pode criar colisões entre códigos e deve aparecer na prévia antes da confirmação.

Valores inesperados de flags devem ser preservados com seus avisos para análise, sem conversão silenciosa para `0`, `1` ou outro padrão. A possibilidade de ler e guardar uma flag desconhecida não significa que ela possa ser escrita no layout de importação do destino. A exportação Prosoft deve bloquear valores inválidos até a revisão; não se deve declarar sucesso mediante correção automática que altere o significado contábil.

Os grupos de relatório do Escritura não são integralmente representados no TXT. Por isso, uma ida e volta por Prosoft não deve ser considerada sem perdas de metadados. Verifique natureza, contas sintéticas/analíticas, hierarquia, centros de custo e códigos após a carga, além da quantidade de registros.

## Verificação e privacidade

A validação estrutural do modelo pode conferir unicidade de acessos e classificadores, existência de pais sintéticos, nomes de até 30 caracteres, máscara por nível, flags, natureza e grupos permitidos. Esses testes não demonstram que um arquivo foi aceito pelo programa Prosoft.

A homologação de ponta a ponta exige importar uma saída revisada numa instalação autorizada do Prosoft e conferir o resultado. Este documento não afirma que essa homologação foi realizada. Não inclua o TXT real, cópias de contas privadas, nomes de clientes ou dados empresariais em testes, logs públicos ou commits.
