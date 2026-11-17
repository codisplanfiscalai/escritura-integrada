# Pagamentos de notas antigas pelo XML original preservado

Base testada: `develop` em `50dbad4381869eea69174f4d111e02b207a147a3`, `0.9.0-dev.44`. A PR68 já está incorporada. Não há alteração nas branches de API, recepção, relatórios ou prévia PDF.

## Problema e comportamento

Documentos importados por versões anteriores podem ter XML original preservado e pagamentos válidos, mas não ter `declared_document_fields`. O rateio nativo usava somente esse snapshot, recusando as notas antigas. O novo fallback recupera apenas os pagamentos em memória, dentro dos serviços existentes de consulta, prévia e execução.

O fallback ocorre somente quando `declared_document_fields` está ausente ou nulo. Um snapshot existente continua autoritativo, inclusive para diagnosticar dados inválidos; não é substituído silenciosamente pelo XML. Não há novo botão, modelo obrigatório, confirmação, reimportação ou migração. O usuário continua selecionando contas explicitamente no mesmo fluxo. Campo/hash de origem inexistente preserva o erro 400 anterior de seleção sem evidência; uma identidade válida cuja origem não possa ser recuperada retorna diagnóstico de fonte indisponível, sem sucesso contábil.

## Verificação da origem

`RetainedPaymentSources` opera na conexão e empresa da solicitação. Um índice de metadados de importações é carregado apenas se houver fallback. A procura exige o mesmo hash de XML, chave e modelo no lote da empresa. Para cada lote candidato, valida também o SHA-256 do contêiner inteiro, antes de usar os leitores limitados existentes de originais/compactados.

O hash real de cada XML é calculado a partir dos bytes preservados. O importador existente relê o documento com a empresa atual, validando namespace, documento completo único, versão, papel da empresa e identidade. O fallback exige chave, modelo e direção iguais aos da nota. Protocolo explicitamente não autorizado/cancelado não é usado como pagamento. Não busca outra versão apenas por ter a mesma chave, nem escolhe arquivos pelo nome; um segundo contêiner com os mesmos bytes exatos pode servir como cópia íntegra.

A leitura reaproveita limites de tamanho, membros, expansão, profundidade, caminhos e parser XML sem DTD/entidades externas. Não extrai caminhos de usuário ou busca arquivos externos. Arquivo ausente, corrompido, metadado divergente, hash incompatível, empresa errada, XML inválido ou somente evento não fornecem evidência para contabilização.

O cache dura somente a operação/empresa. Um ZIP com várias notas é aberto uma vez, e conserva em memória apenas a identidade e os subgrupos de pagamentos, sem guardar cópia integral de itens, endereços ou XML no cache. Snapshots presentes não consultam os originais. Consulta, prévia e execução têm caches separados; perda/corrupção da origem depois da prévia é revalidada na execução.

## Preservação contábil e fiscal

Não há UPDATE da revisão, versão, IDs, CFOP, itens, tributos, competência, dados de origem ou vínculos durante a consulta/prévia. O total escriturado e a classificação revisada continuam sendo os usados pelo serviço contábil. A releitura do original não reclassifica nem sobrescreve a nota.

A saída do fallback é validada pelo mesmo cálculo de pagamentos/troco da PR68. Prévia é somente leitura; a execução é atômica e usa as mesmas contas, permissões, fechamento e idempotência. A contribuição persistida registra `payment_snapshot.evidence_origin=retained_xml` e `source_hash`, além das partidas e demais referências já existentes. A geração altera somente os vínculos que o serviço nativo já criava.

Documentos cancelados/não aptos continuam ignorados pelos critérios existentes. Protocolo cancelado em um original não transforma uma nota antiga inconsistente em movimento. Replay confirmado e estorno da contribuição usam a auditoria existente, sem depender de manter o XML depois da geração; uma chave nova ou mudança de modo não duplica notas vinculadas. A limpeza de importações continua sem apagar lançamentos.

## Testes sintéticos

[Evidência estruturada](evidence/legacy-fiscal-payment-sources.json) contém hashes das fontes e resultados. Nenhum XML, backup ou dado real foi aberto/copiado para este trabalho.

- **213 testes Python em 19 módulos**, sem erros/falhas/skip. Incluem 12 novos casos de legado, rateio moderno/individual/diário, centavos, troco, cache, preservação de revisão/dados, origem simples/ZIP, ausência/adulteração/má formação/tipo inválido, DTD, chave/modelo/empresa/direção, metadados falsificados, protocolo cancelado, cancelamento local, permissões sem acesso a importações, competência fechada/reaberta, transação com uma origem válida e outra ausente, replay, concorrência e estorno parcial. Regressões de importação, revisão, limpeza de lotes, reprocessamento, Prosoft, evidência documental, API e infraestrutura também passaram.
- **213 testes frontend** e build Vite passaram (aviso existente de chunk >500 kB). Não houve mudança no frontend.
- **Chromium 151.0.7922.34 / Playwright 1.62.0, 13 grupos fiscais aprovados**, sem erros JS, com o mesmo comando da CI e sem PYTHONPATH de projeto. Os 12 grupos anteriores permanecem. O novo cenário importa/revisa/escritura duas NFC-e sintéticas e remove somente os snapshots na fixture para representar versões antigas. Pagamentos mistos/dinheiro são recuperados do ZIP com nomes repetidos em pastas distintas. Prévia não altera hashes; geração produz um diário de **531,50**, três linhas e duas origens; perda da resposta e replay não duplicam. Todos os campos das notas (exceto vínculo contábil esperado) e bytes do original são preservados. Captura sintética da prévia inspecionada.
- **Roteiro Chromium de desempenho aprovado**, com 22.597 contas e 183 títulos, orçamentos/paginação existentes preservados. Nenhuma mudança no roteiro de desempenho.
- Dependências declaradas, versão dev.44, compilação Python e whitespace conferidos. Não há comando lint separado no frontend. O contrato antigo de status 400 para notas sem identidade de origem foi preservado sem modificar suas asserções.

Reprodução: instalar dependências declaradas, apontar `ESCRITURA_DATA_DIR` para diretório descartável e `ESCRITURA_DEMO=0` antes de carregar a API. Executar `python -m unittest discover -s tests -p test_fiscal_payment_legacy_sources.py`, além dos módulos listados na evidência. Interface: `node --test frontend/tests/*.test.js`, `npm --prefix frontend run build`, `python scripts/browser_fiscal_sales_accounting.py` e `python scripts/browser_performance.py`. Os roteiros criam seus próprios bancos/servidores locais temporários e aceitam `ESCRITURA_TEST_BROWSER`.

## Limites

Precisa do original da própria empresa e de metadados/hashes coerentes. Não recria XML eliminado, não busca SEFAZ, não certifica assinatura/XSD e não comprova situação fiscal online. Dados armazenados e revisões não são corrigidos automaticamente. Entradas, contas diretas, modelos e relatório diário mantêm a cobertura anterior; não há contabilização automática na importação, inferência de conta, taxa ou baixa financeira.

Suíte backend integral, PostgreSQL, instaladores e dados/escala de produção não foram testados localmente. A CI do head publicado deve ser conferida separadamente. A correção não foi aplicada a instância real; sem merge, release, implantação ou obrigação transmitida.
