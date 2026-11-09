# Escrituração fiscal — incremento 0.8

Escopo desta etapa: CFOP, associações por empresa, importação com escrituração fiscal direta e edição posterior. O pedido de plano de contas foi suspenso por orientação expressa; nenhum importador ou plano contábil novo integra esta entrega.

## Referência CFOP verificada

A página [Anexo II do CONFAZ](https://www.confaz.fazenda.gov.br/legislacao/ajustes/sinief/cfop_cvsn_1-6.24) foi lida integralmente em 09/11/2026. Foram identificados **619 códigos de operação**, **76 grupos** e **620 redações**: o código 7.667 possui duas redações com períodos explícitos. A redação anterior vale de 01/06/2024 a 31/01/2026; a alteração pelo Ajuste SINIEF 39/25 tem efeitos a partir de 01/02/2026. Grupos como 1.000 e 1.100 não são códigos de operação selecionáveis.

O texto consultado está em `referencias/cfop-confaz-20261109.txt`. `scripts/build_cfop_reference.py` gera `app/data/cfop-confaz-20261109.json`, com URL, data da consulta, hash do texto, títulos, notas explicativas e vigências da **redação**. Essas datas não são apresentadas como datas originais de criação dos códigos. O teste reconstrói o JSON e confere sua igualdade, cobertura e seleção histórica.

O Portal NF-e anuncia Tabela CFOP publicada em 04/09/2026 e IT 2023.002 v2.10. O acesso aos seus downloads entrou em redirecionamento nesta execução. Seus indicadores de autorização DF-e não foram extraídos nem inventados. A fonte incorporada é o Anexo II do CONFAZ, não uma certificação dos indicadores NF-e. A referência não aplica alíquotas, incidência ou direito a crédito.

Fiscal → **CFOP e associações** permite pesquisar código, título e nota, filtrar sentido e data, ler a fonte e cadastrar a referência na empresa. A cópia preserva os cadastros existentes; alterações da empresa não modificam a referência compartilhada. A fonte e as notas continuam consultáveis. As vigências anteriores à redação-base dependem de outra referência histórica.

## Associações e importação

Na aba **Associações de importação**, escolha sentido, modelo, CFOP original, CFOP de escrituração, vigência, responsável e fundamento. Associações ativas do mesmo escopo não podem ter vigências sobrepostas. Uma associação específica do modelo tem precedência sobre a opção de todos os modelos; ambiguidades bloqueiam a escrituração. Alterações ficam no histórico e não atualizam documentos já importados.

A opção padrão da interface fiscal é **Importar e escriturar no Fiscal**, quando o usuário possui a permissão de escriturar. O percurso é selecionar XML/SPED/compactado suportado → analisar → preparar os CFOPs → confirmar o lote → abrir a escrituração. Não é necessário conferir e escriturar cada nota separadamente. A alternativa de importar para conferência individual permanece disponível.

A preparação apresenta diagnósticos por documento. Associações da empresa são aplicadas somente dentro da vigência. O operador também pode indicar CFOPs apenas para aquele lote; essa escolha não altera as associações permanentes. Não há conversão presumida do CFOP do emitente para o CFOP de entrada. Modelos ou cenários não reconhecidos permanecem recusados.

A confirmação revalida hash da prévia, preparação, empresa, exercício, permissões, competências e apurações. Uma mudança de associação invalida a preparação antiga. Somente os documentos selecionados e elegíveis são gravados; uma falha reverte a transação completa. A recepção do arquivo continua separada da efetivação dos movimentos.

XMLs de homologação, sem protocolo associado ou com totalizadores/cenários que exigem decisão individual não são escriturados diretamente. A validação estrutural dos leitores existentes continua; não foi acrescentada consulta SEFAZ nem validação criptográfica. A preparação não certifica validade legal do documento.

O lote direto grava exclusivamente a escrituração fiscal. Não gera títulos, baixas ou partidas contábeis implicitamente. A integração explícita já existente permanece disponível pelo fluxo próprio.

Para compatibilidade, a API de confirmação sem `posting_mode` conserva o modo anterior de conferência. A interface envia `posting_mode=book` e o `posting_hash` retornado pela preparação. `posting_mode=pending` seleciona o fluxo anterior. Uma confirmação já realizada não pode ser repetida com outro modo ou seleção.

## Edição, conferência e rastreabilidade

Documento escriturado sem efeitos vinculados pode ser editado, com motivo, controle de versão e permissões de editar/escriturar. Permanece escriturado após salvar. Fiscal fechado ou apuração finalizada impede alterar a origem; tanto o período anterior quanto o novo são conferidos se a data mudar. A identidade e o sentido do documento importado são preservados.

Partidas, títulos ativos ou cadeia de renegociação impedem a edição direta: deve-se usar a reversão dos efeitos já implementada. Não são alterados saldos de outro módulo silenciosamente.

Originais, hashes, CFOP da origem, associações aplicadas e suas versões/retratos permanecem preservados. A importação direta é identificada para conferência posterior e não grava uma revisão humana fictícia. A conferência posterior pode ser registrada sem desfazer a escrituração. Uma nova edição invalida essa conferência e sinaliza alterações nas memórias/auditorias dependentes.

Reimportar o mesmo original após uma correção preserva a revisão atual e não cria outra nota. Conteúdo original diferente com a mesma identidade continua produzindo conflito, sem sobrescrita automática.

## Validação e limites de distribuição

Os testes de domínio/API estão em `tests/test_fiscal_import.py`; cobrem origem, reimportação, vigências, permissões, isolamento, atomicidade, bloqueios e efeitos vinculados. `scripts/browser_fiscal.py` percorre cadastro da associação, importação já escriturada, edição motivada, reimportação e conferência posterior pela interface. Há capturas em 1440 × 768 e 390 pixels. Os resultados efetivamente executados devem ser consultados nos relatórios e no run do commit testado.

A referência é incluída no Docker e nos dois pacotes PyInstaller. Os smokes de distribuição consultam a API CFOP e verificam a presença dos 619 códigos. A presença do código desses testes não substitui seu resultado nos runners nativos.

Não houve migração do esquema nem substituição de cadastros ou bases. Associações usam o registro de cadastros existente, sob um tipo interno exclusivo, com empresa, versão, autor e auditoria. Plano contábil, motor tributário legal completo, novos leiautes e transmissão de obrigações não fazem parte deste incremento.
