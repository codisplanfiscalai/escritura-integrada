# Terceiros nas partidas contábeis

As partidas aceitam `participant_id` de cadastro participante ativo da própria empresa. A regra explícita `prosoft.entries` do plano é respeitada: 1 sem terceiro, 2 opcional, 3 obrigatório. Contas nativas sem metadado permanecem opcionais. Não há inferência por nome de conta, fornecedor ou CNPJ.

CSV `journals-v2` e `openings-v2` acrescentam `participant_code` ao final do leiaute v1. O código é resolvido somente dentro da empresa. A identidade do lançamento continua usando o prefixo v1: mudar de leiaute não duplica lançamentos. Conteúdo diferente com a mesma identidade gera conflito. Registros antigos não são automaticamente preenchidos.

O comando Contabilizar em documento já escriturado chama `POST /documents/{id}/account`. Requer leitura fiscal e criação contábil. Cria o lançamento e associa ao documento numa única transação, sem reverter documento, gerar títulos, alterar datas ou versão fiscal. O período contábil precisa estar aberto quando os bloqueios da empresa estão habilitados. Uma repetição da mesma intenção retorna o resultado anterior. Outra intenção é rejeitada se o documento já possui lançamento.

O terceiro vem do vínculo explícito do documento. Documento de entrada identificado sem vínculo exige correção cadastral antes da contabilização. Não se escolhe fornecedor automaticamente por semelhança. Estornos preservam o vínculo histórico.

Limites desta etapa: sem preenchimento retroativo, sem alteração da integração de baixas financeiras, sem homologação na Prosoft, sem dados reais ou alteração de produção.

A exportação CTBLCTOS resolve o terceiro pelo vínculo de cada partida e exige código de destino confirmado por participante. O código fixo da conta não substitui esse vínculo. Contas com regra obrigatória não podem ser exportadas no modo sem terceiro. A prévia inclui esse mapeamento na impressão digital.

A inicialização verifica a existência real da coluna antes da migração e faz backup consistente mesmo quando o banco já informa schema 6. Backups e restauração preservam todas as colunas SQLite. Os leiautes v2 participam do mesmo bloqueio de reimportação de movimentos excluídos dos leiautes v1.
