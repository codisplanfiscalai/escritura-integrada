# Busca e download automático de NF-e e NFS-e

Implementação incremental sobre develop 0.9.0-dev.61, preservando as correções da PR86 e a evolução posterior da branch (incluindo os relatórios de balancete). Sem troca de banco, versão de migração, certificado ou criptografia.

## Cadastro da empresa

Em **Cadastro → Empresas → Recepção fiscal → Busca e download automático de XMLs**, cada serviço possui:

- Habilitar/desabilitar a automação, independentemente do outro serviço.
- Intervalo com seleção de **minutos, horas ou dias**, padrão **24 horas** (1440 minutos na API). Exemplos: 720 = 12h; 2880 = 48h. Permitidos de 1 a 525600 minutos, sem suprimir pausas exigidas pelo serviço.
- Situação, próxima tentativa, última coleta concluída, lotes e itens da execução.
- Atualização da situação e ação **Revisar e reagendar** em bloqueios.

O intervalo é a periodicidade entre coletas concluídas; não é o timeout de uma conexão HTTP e não é uma pausa obrigatória entre cada lote positivo. A rede continua com os prazos finitos já existentes no transporte.

As automações começam **desabilitadas**, preservando instalações existentes. Ao habilitar/salvar, a primeira coleta é agendada imediatamente em segundo plano. Salvar A1 ou os parâmetros antigos de ambiente continua sem disparar consulta. Não é necessário cadastrar novamente o certificado.

As duas automações funcionam simultaneamente: por exemplo, NF-e a cada 48h e NFS-e a cada 24h. A execução utiliza o ambiente salvo no cadastro e a inscrição completa da empresa, sem dividir o cursor de duas filiais.

## Continuidade, pausas e retomada

A automação usa o mesmo `ReceptionService`, recibos, originais e cursor da consulta manual. O estado do agendamento/lease é persistido no namespace próprio `reception-automation-v1` de `operations`; nenhuma tabela ou migração anterior é reescrita.

O worker integra o lifespan FastAPI, tanto no servidor/Docker quanto no aplicativo tray. Funciona com a tela fechada, enquanto o processo estiver ativo, e retoma o estado após reinício. Não instala serviço Windows nem depende do navegador. O modo demo não inicia o worker fiscal.

A cada fatia o worker processa um lote por identidade de coleta e cede execução às outras empresas/serviços. Lotes positivos continuam do cursor confirmado sem esperar 24h entre páginas. Não existe teto total de documentos que encerre o histórico antecipadamente.

- Fim fiscal explícito encerra a coleta atual e agenda a próxima em `max(conclusão + intervalo escolhido, pausa do serviço)`.
- `Retry-After` recebido pelo transporte é respeitado também em lotes positivos NF-e e NFS-e.
- NF-e mantém as regras existentes para 137, 656 e esgotamento ultNSU/maxNSU; ADN mantém ausência explícita E2220 e sua pausa conservadora de esgotamento.
- Uma pausa não é conclusão. Erro temporário agenda uma próxima tentativa, respeitando o intervalo escolhido e o prazo do serviço, com bloqueio após repetidas falhas.
- Retorno recusado, inválido ou inconclusivo bloqueia com motivo; não simula download e não pula XMLs. A ação explícita de reagendar preserva o recibo anterior e o cursor; não executa emissão ou manifestação.
- Desabilitar impede novos lotes; o lote já transmitido pode terminar e seu XML ser arquivado. Nenhum documento é excluído.

Leases persistentes e o coordenador já existente impedem duas instâncias desta base de transmitirem o mesmo lote simultaneamente. Se houver crash depois de gravar o recibo/cursor e antes de atualizar os contadores do agendamento, a retomada lê a mesma tentativa idempotente e contabiliza uma vez, sem nova requisição. Uma tentativa antiga ainda em andamento/inconclusiva não é reenviada automaticamente com outra identificação.

Ambiente, A1, inscrição, ajuste manual de NSU ou permissões alterados invalidam a configuração do job; o worker bloqueia até a revisão explícita. Desativação/reconfiguração durante um lote não pode ser sobrescrita pelo worker anterior. Antes de cada lote são revalidados usuário ativo, acesso à empresa, edição de empresa e permissões de consulta/importação fiscal. Não se depende da sessão de navegador que habilitou a automação.

## Emitidas e recebidas: cobertura real

**NFS-e/ADN:** a coleta não filtra somente recebidas. Arquiva os documentos que o serviço disponibiliza ao prestador, tomador e intermediário. As views existentes classificam emitidas, recebidas e ambas pela inscrição completa no XML, com originais e versões preservados. A coleta não presume que todo documento do portal Web esteja disponível pela API.

**NF-e/distribuição:** consulta os documentos distribuíveis para o interessado, inclusive eventos relacionados às suas notas. Contudo, o serviço **não fornece ao próprio emitente o XML da NF-e que ele emitiu**. Não foi inventado um endpoint ou apresentado resumo/evento como XML completo.

Para as **NF-e emitidas**, permanece disponível o fluxo existente de **Importações fiscais**, que aceita os XMLs do emissor e os classifica como saída quando a empresa é emitente. Automatizar a obtenção desses arquivos exige definir uma fonte efetiva do emissor (integração ou diretório de exportação autorizado). Esta PR complementar não cadastra uma fonte fictícia nem faz varredura arbitrária no disco do servidor.

A automação não manifesta documentos para liberar XMLs, não emite NF-e/NFS-e, não escritura, não cria contas a pagar/receber e não altera competências fechadas.

Fontes oficiais:

- [MOC — Distribuição NF-e, tabela de documentos por ator e regra 641](https://moc.sped.fazenda.pr.gov.br/NFe_NFCe/NFe_NFCe/NFeDistribuicaoDFe.html).
- [Manual contribuinte ADN v1.1](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-municipios-apis-adn-sistema-nacional-nfs-e-v1-1-20261103.pdf).

## Convivência com outros buscadores

Aumentar o intervalo ou desabilitar um coletor reduz consultas, mas não coordena automaticamente softwares/bases independentes. A reserva do Escritura cobre somente esta base. Para o mesmo CNPJ/ambiente, combine quem coleta, sequência e intervalos com o buscador externo, ou importe os XMLs obtidos por ele. Não zere o NSU nem a pausa oficial para forçar nova busca.

## API interna

- `GET /api/companies/{cid}/reception-automation`: configurações e situação por serviço; exige consulta à empresa.
- `PUT /api/companies/{cid}/reception-automation/{provider}`: `{version, enabled, interval_minutes}`; exige edição da empresa e consulta/importação fiscal, sessão/CSRF e revisão otimista.

Empresa, ambiente, inscrição, URL e certificado não são aceitos livremente no corpo. Os jobs usam apenas a configuração canônica do servidor. A API não devolve PFX, senha ou chave. Diagnósticos de falha são mensagens internas; erros brutos do transporte não são expostos.

## Validação

Testes sintéticos de API, banco e worker cobrem dois serviços independentes, padrão de 24h, vários lotes, intervalo maior/menor, pausas oficiais, reinício, replay após commit, tentativa inconclusiva, concorrência, desativação em andamento, configuração/permissão revogadas, escopo empresarial e execução sem sessão de navegador. Testes Vue cobrem isolamento dos formulários, alteração de empresa durante resposta pendente e acesso somente leitura. Build da interface verificado.

Não houve consulta fiscal externa, ativação em produção ou teste de uma integração com emissor NF-e real. O novo head deve passar pelos workflows nativos e de infraestrutura existentes; testes locais com certificado/transporte sintéticos não equivalem à homologação do serviço.

Resultados locais desta continuação:

- Regressão ampliada: **134 testes percorridos, 133 aprovados e um skip**; contratos, recepção, configuração, credenciais, cofre, proxy e ciclo de vida desktop.
- Suíte atual da automação: **16 testes aprovados**, incluindo loop sem sessão do navegador, disputa de workers, retorno NF-e com Retry-After e replay sem redownload.
- Interface: **241 testes aprovados**; build Vite aprovado, com aviso preexistente de chunks acima de 500 kB.
- Os testes da automação integram o CI existente. Nenhum teste foi dispensado para habilitar a funcionalidade.
