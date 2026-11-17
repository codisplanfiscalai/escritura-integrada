# Histórico local da recepção

Os 20 itens na tela são tamanho de página, não retenção máxima. Os recibos e os originais continuam registrados; cada avanço do cursor depende da gravação transacional do retorno. A coleta externa permanece separada da navegação no acervo e da escrituração.

A rota local `GET /reception/{provider}/receipts` pagina o histórico por empresa, ambiente e exercício, sem abrir/descomprimir XMLs, carregar certificado ou consultar o Fisco. A interface descarta respostas de contexto anterior e permite navegar além dos 20 recibos recentes.

Este incremento não implementa coleta automática nem elimina o custo da reconstrução integral do acervo de documentos. O próximo incremento deve tratar índice documental persistente com migração/backfill, integridade e paginação SQL. Não substitui validação externa dos adaptadores.
