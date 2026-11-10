# Importação, reclassificação e livro analítico

Entrega de desenvolvimento sobre `develop` 0.8.0-dev.16. Não altera uma base operacional nem publica instaladores por si só.

## Originais e prévia

- PDF reconhecido dentro de ZIP/7z/RAR é acessório ignorado, com nome, tamanho e SHA-256 preservados. Não gera movimento. PDF avulso, executáveis e formatos incompatíveis continuam recusados.
- Avisos genéricos são agrupados com contagem e origens. Um lote de 300 XMLs e 300 PDFs não fica impedido apenas pelos avisos. Permanecem limites de tamanho, expansão, membros, proporção de compressão, profundidade, criptografia, caminhos e integridade.
- Emissão e movimentação declaradas são preservadas. A chegada efetiva da mercadoria (`receipt_date`) é informada pelo usuário, separada da emissão, da movimentação XML e da data de escrituração. Pode ser corrigida na importação, no reprocessamento e na escrituração, com motivo, versão e bloqueios de período. Copiar a chegada para a escrituração exige ação explícita; não se presume chegada por haver XML. Entrada cuja escrituração foi sugerida apenas pela emissão exige confirmação explícita da competência. A mera existência de XML não comprova recebimento.
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

## Cobrança XML e contas a pagar

A prévia preserva `cobr/fat` (número, bruto, desconto e líquido) e cada `cobr/dup` (número, vencimento e valor), com campos originais e fonte. Sequência técnica não substitui número fiscal ausente. Sem cobrança não há erro nem parcelas inventadas. Cobrança incompleta ou inconsistente gera aviso financeiro; a opção fiscal permanece disponível sem gerar contas a pagar.

**Gerar contas a pagar das parcelas do XML** começa desligado e exige escolha explícita. A confirmação informa quantos títulos serão criados ou preservados. Essa opção exige permissão financeira, período disponível e parcelas válidas. A geração é transacional com a importação: falha não deixa metade das notas ou parcelas gravadas. Não cria baixa, pagamento, liquidação bancária nem partida contábil.

Títulos ficam vinculados à nota e empresa, com identificador estável por documento e duplicata, independente da revisão ou do lote. Reimportação e reprocessamento não criam outro conjunto. Títulos manuais, alterados, baixados, cancelados ou renegociados exigem revisão, sem recriação automática. A reclassificação pode preservar títulos XML íntegros quando valores e identidade financeira não mudam.

Lotes antigos podem recuperar somente cobrança/fatura/parcelas a partir do XML original verificado, sem substituir valores, itens, datas ou IDs fiscais. Se a origem necessária estiver indisponível, a geração financeira é bloqueada para conferência. Vencimento não é data de pagamento e a soma financiada não é presumida como o total da nota.

## Condição opcional para compras sem cobrança

O gerador alternativo começa desligado. O usuário seleciona notas ou informa CNPJs dos fornecedores presentes na prévia, escolhe explicitamente emissão ou chegada efetiva como base e revisa prazo (30 dias por padrão), responsável e motivo. Gera uma parcela por nota, não uma fatura consolidada entre notas. A ausência de chegada efetiva bloqueia a base correspondente; não há substituição silenciosa por emissão ou competência.

A prévia distingue a parcela escolhida pelo usuário da cobrança original. Valor e vencimento podem ser ajustados com justificativa. Qualquer cobrança original, inclusive FAT incompleta ou duplicata inconsistente, impede a substituição por essa regra. Lotes legados sem comprovação da ausência de cobrança precisam recuperar o XML original antes da geração alternativa. Operações sem natureza de compra reconhecida, como bonificação, devolução ou remessa, exigem tratamento manual. A opção exige permissão financeira e período aberto, mantém empresa e documento vinculados e não cria pagamento, baixa ou contabilização.

O identificador financeiro é estável por documento. Repetir a geração preserva os títulos íntegros. Alterar condição, vencimento, valor ou base de um título já gerado exige revisão manual; editar chegada/competência posteriormente não atualiza silenciosamente contas a pagar. O reprocessamento fiscal pode preservar títulos íntegros sem regenerá-los.

A referência local GeradorSPED foi conferida quanto a preservação de DUP/FAT, seleção explícita e cálculos em centavos. Seu fallback entre escrituração e emissão não foi reproduzido: aqui a chegada efetiva é um dado independente informado pelo usuário.

## Linhas e livros

O motor gera parcelas por CFOP, CST/CSOSN, origem, alíquota e tratamento, com Decimal e conservação exata do total. O cabeçalho mantém vNF uma única vez. C190 existente não é confundido com itens nem somado ao cabeçalho novamente.

Há revisão opcional de grupos por item com fonte, responsável e motivo. Separar conserva critérios automáticos. Consolidar exige tratamento explícito e compatibilidade, preserva todas as classificações declaradas e deixa campos heterogêneos sem valor único fictício. Coincidência de montantes não comprova qual item pertence a uma linha de um livro externo.

IPI econômico, tributos declarados e campos fiscais do livro são dimensões próprias. Ausência ou cobertura parcial não é apresentada como informação completa nem convertida em crédito. Perfis são explícitos, fundamentados e sujeitos à vigência. O perfil Outras = parcela contábil menos IPI não é regra universal do Simples Nacional.

PDF e Excel usam o resultado analítico da consulta, com cabeçalhos únicos, parcelas, cobertura e rastreabilidade. Filtro CFOP soma somente as linhas correspondentes. NCM seleciona a linha fiscal inteira, com aviso de que ela pode conter outros NCMs. Ver `LIVRO_ANALITICO.md`.

## Reprocessar sem excluir

Lotes existentes oferecem prévia antes/depois, seleção e confirmação transacional. Reprocessamento mantém IDs, origem, valores e edições manuais; atualiza classificação, competência explícita, perfis e linhas. A data atual é preservada como ponto de partida, em vez de retornar à emissão. A edição posterior envia somente campos editáveis efetivamente alterados, sem transformar metadados de leitura em alterações financeiras. Períodos fechados exigem reabertura; apurações finalizadas exigem sua rotina própria de reabertura. Efeitos contábeis vinculados ou títulos modificados/baixados continuam protegidos, sem reescrever valores ou vencimentos para acomodar uma alteração fiscal.

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

Plano compartilhado sem cópia integral, tabelas globais informativas, biblioteca de padrões deriváveis e terceiros com identidade global foram integrados nesta etapa. Consulte `PLANO_CADASTROS_GLOBAIS.md` para operação, limites e validação. O TXT 050 real permanece privado e exige revisão de suas propriedades; modelos genéricos não o substituem. O CNAE do padrão é validado na importação, não convertido em condição automática de cálculo futuro. O catálogo contextual de reclassificação continua separado desses módulos.

Para validar a interface e o reprocessamento, siga `ROTEIRO_TESTE_IMPORTACAO.md`.

A revisão financeira posterior deve distinguir FITIDs repetidos, conta, data, valor e ocorrência. Aplicações, empréstimos, vencimentos e pagamentos não são tratados como equivalentes. Esta entrega não altera o leitor financeiro.
