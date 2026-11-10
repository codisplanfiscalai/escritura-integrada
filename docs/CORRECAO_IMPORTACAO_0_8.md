# Importação, reclassificação e livro analítico

Entrega de desenvolvimento sobre `develop` 0.8.0-dev.16. Não altera uma base operacional nem publica instaladores por si só.

## Originais e prévia

- PDF reconhecido dentro de ZIP/7z/RAR é acessório ignorado, com nome, tamanho e SHA-256 preservados. Não gera movimento. PDF avulso, executáveis e formatos incompatíveis continuam recusados.
- Avisos genéricos são agrupados com contagem e origens. Um lote de 300 XMLs e 300 PDFs não fica impedido apenas pelos avisos. Permanecem limites de tamanho, expansão, membros, proporção de compressão, profundidade, criptografia, caminhos e integridade.
- Emissão e movimentação declaradas são preservadas. Entrada cuja escrituração foi sugerida apenas pela emissão exige confirmação explícita da competência. A mera existência de XML não comprova recebimento.
- Data, classificação, destinação e perfis são revisáveis antes de confirmar. Alteração invalida a preparação. O servidor revalida exercício, períodos, apurações, permissões, regras e hash na transação.
- vNF, vNFTot e sua diferença permanecem separados. XML com totalizadores RTC exige decisão explícita sobre a base vNF, com fonte, responsável e motivo. Isso não valida juridicamente RTC, XSD, assinatura ou eventos posteriores. Outros bloqueios de autorização/protocolo não são removidos.
- DANFE/DANFC-e/DACTE usa o XML original verificado por hash. O renderizador pode recusar XML incompleto. Visualizar não cria movimentos.

## Reclassificação contextual

O catálogo global versionado oferece 40 propostas de compra regular/ST para revenda, industrialização, uso/consumo e ativo. A empresa importa uma cópia, revisa os pares e pode personalizá-los, preservando versão de origem, responsável e auditoria.

Regras específicas por empresa, modelo, sentido, vigência, destinação, NCM ou produto prevalecem sobre o fallback. Ambiguidade e incompatibilidade geográfica impedem aplicação automática. O fallback exige destinação e UF compatíveis; não troca cegamente o primeiro dígito do CFOP.

Devolução, remessa, transferência, bonificação, frete e importação exigem contexto/regra específica. Há avisos sobre associações de naturezas diferentes. CFOP não determina automaticamente crédito, CST, alíquota ou incidência. Códigos originais e a regra aplicada são preservados por item.

## Cadastros e identidade

Participantes identificados são vinculados por CPF/CNPJ na empresa. Papéis são acumulados sem substituir dados revisados. Consumidor anônimo da NFC-e não vira pessoa fictícia. Campos cadastrais disponíveis, transportador e GTIN são preservados sem preencher ausências artificialmente.

Produtos e serviços são separados. Itens recebem `master_id` por emitente + código original quando há dados suficientes e permissão. Ainda não há equivalência automática entre código de fornecedor e SKU próprio. Negação de criação/edição cadastral preserva o documento com aviso, sem escrita indevida.

Chave/identidade é única por empresa. Reimportação e confirmações concorrentes não criam outro cabeçalho. XMLs com hashes diferentes e campos coincidentes conservam múltiplas fontes e geram aviso, sem presumir divergência fiscal apenas pelo hash. Conteúdo divergente não é consolidado silenciosamente. Eventos e XMLs não autorizados não viram outra nota por conterem uma chave.

## Linhas e livros

O motor gera parcelas por CFOP, CST/CSOSN, origem, alíquota e tratamento, com Decimal e conservação exata do total. O cabeçalho mantém vNF uma única vez. C190 existente não é confundido com itens nem somado ao cabeçalho novamente.

Há revisão opcional de grupos por item com fonte, responsável e motivo. Separar conserva critérios automáticos. Consolidar exige tratamento explícito e compatibilidade, preserva todas as classificações declaradas e deixa campos heterogêneos sem valor único fictício. Coincidência de montantes não comprova qual item pertence a uma linha de um livro externo.

IPI econômico, tributos declarados e campos fiscais do livro são dimensões próprias. Ausência ou cobertura parcial não é apresentada como informação completa nem convertida em crédito. Perfis são explícitos, fundamentados e sujeitos à vigência. O perfil Outras = parcela contábil menos IPI não é regra universal do Simples Nacional.

PDF e Excel usam o resultado analítico da consulta, com cabeçalhos únicos, parcelas, cobertura e rastreabilidade. Filtro CFOP soma somente as linhas correspondentes. NCM seleciona a linha fiscal inteira, com aviso de que ela pode conter outros NCMs. Ver `LIVRO_ANALITICO.md`.

## Reprocessar sem excluir

Lotes existentes oferecem prévia antes/depois, seleção e confirmação transacional. Reprocessamento mantém IDs, origem, valores e edições manuais; atualiza classificação, competência explícita, perfis e linhas. A data atual é preservada como ponto de partida, em vez de retornar à emissão.

Versões, configuração, regras, empresa e fontes entram no hash. Concorrência, períodos fechados, apurações finalizadas e efeitos vinculados podem impedir a operação. Cópias equivalentes da mesma nota resultam em uma atualização; decisões conflitantes precisam ser resolvidas na prévia. Documento excluído nunca é recriado. O suporte automático atual exige NF-e/NFC-e com itens correspondentes; outros casos seguem revisão individual.

## Controle de pacotes

O controle de lotes nunca exclui documentos, lançamentos, títulos ou movimentos gerados.

- Arquivar/restaurar histórico é reversível, preserva arquivos e libera zero bytes.
- Remover originais exige prévia, permissão específica, confirmação irreversível, retenção e ausência de proteção por evidência fiscal/auditória única. Metadados, dados normalizados, hashes e vínculos são conservados. Backups anteriores não são apagados.
- Lotes fiscais confirmados com fonte única permanecem protegidos contra purga de arquivos. Não se promete remover todos os pacotes vinculados; o histórico pode ser arquivado.
- A política periódica começa desligada e funciona com a aplicação em execução. Usa idade de importação, intervalo UTC e revalida permissões do configurador a cada execução. Não atua sobre pacotes exclusivamente financeiros.

Backups reconhecem originais removidos somente quando há tombstone consistente; vazios sem essa evidência continuam sendo corrupção. Nesta versão, reenviar o mesmo pacote purgado retorna 410 e não restaura seus bytes nem repete movimentos. Eventual recuperação exige backup anterior em pasta separada.

Essa rotina é separada da exclusão de movimentos existente. Não oferece opção de apagar lançamentos ao limpar um pacote.

## Verificação e limites

Os testes usam bases temporárias e fixtures fictícias. Validação documental adicional usa referências autorizadas somente no ambiente privado, sem colocá-las no código, nos testes públicos ou no pacote de distribuição. Uma referência externa pode agrupar itens por decisões que não são inferíveis do XML; esses casos permanecem explícitos para revisão, sem forçar equivalência.

O script `scripts/browser_import_review.py` cobre upload, PDF, edição, Cancelar e confirmação em uma instalação temporária. Neste executor, a aceitação visual do aplicativo ficou bloqueada pela falha de sockets do Chromium e pela inacessibilidade do servidor local no navegador compartilhado. Não se afirma homologação visual/desktop nativa. PDFs sintéticos dos livros foram renderizados e inspecionados separadamente.

Build e suítes aplicáveis devem ser reexecutados no commit final. Instaladores Windows/macOS, CI remoto e validação do fluxo real antes de uso operacional continuam necessários. Nenhum push, merge ou release é implícito nesta entrega.

Plano de contas global/050, catálogos globais editáveis e biblioteca tributária global independente constam em `PLANO_CADASTROS_GLOBAIS.md`; não foram implementados integralmente neste patch. O catálogo de propostas de reclassificação descrito acima já existe, mas não substitui esses cadastros.

A revisão financeira posterior deve distinguir FITIDs repetidos, conta, data, valor e ocorrência. Aplicações, empréstimos, vencimentos e pagamentos não são tratados como equivalentes. Esta entrega não altera o leitor financeiro.
