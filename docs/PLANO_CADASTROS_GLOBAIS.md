# Cadastros globais e padrões fiscais

Os módulos descritos abaixo estão implementados na revisão em desenvolvimento do PR 11. A publicação de um instalador exige o gate conjunto e a CI da revisão final. Esta documentação não declara homologação tributária ou equivalência integral com a Prosoft.

## Plano contábil compartilhado e plano próprio

Uma versão global guarda a definição, os metadados e a origem uma única vez. A empresa pode adotar essa versão em modo compartilhado, que é a opção inicial do diálogo, sem copiar integralmente suas contas ou seu arquivo original para a empresa. A consulta apresenta o plano completo; somente o uso de uma conta cria uma referência técnica local para preservar as chaves dos lançamentos. Ler ou pesquisar não deve materializar contas.

A opção de plano próprio é explícita. Pode duplicar o plano inteiro ou, se escolhido pelo usuário, somente contas usadas e seus ancestrais existentes necessários. Uma cópia parcial vazia não representa uma cópia integral. As contas próprias podem ser adaptadas sem mudar outras empresas. IDs históricos, aliases já utilizados, acessos e classificadores originais permanecem rastreáveis. Classificadores repetidos não são identidade de conta e não devem ser renumerados ou descartados.

Empresas existentes não são reassociadas automaticamente. Uma nova versão global também não modifica versões ou movimentos anteriores silenciosamente. Prévia, permissões, revisão de propriedades e confirmação são necessárias para publicar e adotar um plano. Os seletores usam busca e uma janela de opções, mantendo a seleção atual, sem cortar a definição do plano.

**050 é o TXT contábil fornecido pelo usuário, não um registro I050.** O código oferece a importação e o compartilhamento desse plano, mas não publica o arquivo privado no repositório ou no instalador. Os modelos genéricos já existentes não são o 050. Sua carga real exige conferência de máscaras, natureza, indicadores, acessos, metadados e conflitos apresentados. A documentação histórica registra 22.596 acessos e 428 classificadores distintos; o teste sintético de igual porte não substitui a validação da íntegra privada.

Detalhes: [intercâmbio e plano global](PLANO_CONTAS_INTERCAMBIO.md).

## CFOP e códigos de serviço globais

A referência oficial de CFOP é compartilhada, com redações e origem preservadas. O painel global permite editar informações e alíquotas declaradas, incluindo adicionar ou remover valores, com motivo, versão e histórico. Valores sem contexto tributário ou vigência comprovada permanecem informativos. Não definem incidência, crédito ou cálculo automaticamente.

Códigos de serviço identificam tabela/sistema e jurisdição. O mesmo código municipal e nacional não é tratado como serviço equivalente. Catálogos locais legados continuam identificados como escolhas da empresa, sem promoção de seus dados privados. As associações entre CFOP original e escrituração e os padrões contextuais de compra continuam empresariais. O catálogo de propostas de reclassificação não é uma biblioteca de alíquotas.

Detalhes: [tabelas e biblioteca fiscal global](BIBLIOTECA_FISCAL_GLOBAL.md).

## Biblioteca global de padrões fiscais

A biblioteca global é independente dos modelos legados que contêm snapshots empresariais. Permite publicar versões, criar um padrão baseado em outro com linhagem preservada e importar uma cópia para a empresa. Regime, segmento, atividade declarada, filtro CNAE opcional, jurisdição das regras e vigência ajudam a selecionar e revisar o contexto.

As estruturas iniciais são propostas sem alíquotas presumidas. Farmácia pode ser uma atividade declarada de um padrão próprio; o nome ou o CNAE não cria tratamento tributário. A importação compara regime, atividade confirmada, CNAE quando informado e vigência, mostra prévia e cria regras locais em rascunho e inativas. Alterar a biblioteca não altera as cópias anteriores.

O filtro CNAE é uma guarda da **importação do padrão**, não uma condição automaticamente adicionada ao cálculo futuro. O histórico exibe origem e avisos de alteração do enquadramento. As regras locais precisam de revisão e condições próprias antes de ativação. Não se afirma apuração completa de DAS, monofásico, substituição tributária, benefícios ou operações especiais somente por selecionar um modelo ou CFOP.

## Terceiros e cadastros da empresa

A identidade global mínima distingue CPF, raiz de CNPJ e estabelecimentos por CNPJ completo. Dados, papéis, contatos, inscrições e movimentos permanecem vinculados à empresa autorizada. Compartilhar uma identidade não concede acesso às relações de outras empresas.

Reutilizar dados cadastrais exige leitura da origem e edição no destino, seleção de campos, prévia e confirmação. Múltiplas inscrições estaduais preservam UF, situação e histórico, sem inventar isenção quando a informação estiver ausente. Correção de identidade usa substituição auditada; documentos e títulos históricos mantêm seus IDs e vínculos, sem liberar novas escolhas do cadastro substituído.

Produtos e serviços continuam separados e locais à empresa. Importação conserva identificação de emitente e código original para rastreabilidade; não inventa equivalência entre código do fornecedor e SKU próprio. Há consulta dos movimentos vinculados. Essa consulta não constitui uma conciliação de estoque ou margem já homologada.

Detalhes: [terceiros globais e rastreabilidade](TERCEIROS_GLOBAIS.md).

## Migração e verificação

As migrações globais concluem antes da marca de esquema 6. Uma falha não deve marcar a atualização como pronta; a retomada conserva o backup anterior à atualização. IDs, vínculos, totais, originais e hashes entram nas verificações de migração e backup/restauração.

Testes usam bases temporárias e fontes sintéticas. Fontes empresariais privadas permanecem fora do repositório e dos artefatos públicos. O resultado de cada gate vale somente para a revisão indicada; uma suíte focada ou um build isolado não substitui a CI conjunta nem a aceitação visual dos fluxos finais.
