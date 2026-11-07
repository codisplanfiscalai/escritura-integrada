# Fixtures sintéticas dos renderizadores

`auditor_cte.xml`, `auditor_mdfe.xml` e `auditor_nfce.xml` preservam a estrutura dos exemplos de testes do projeto [BrazilFiscalReport](https://github.com/Engenere/BrazilFiscalReport) (LGPL-3.0), usado pelo renderizador 1.3.1. Dados de identificação, nomes, endereços, textos livres, chaves, protocolos, placas e datas foram substituídos por valores fictícios; assinaturas digitais foram removidas. Modelo do fixture MDF-e ajustado para 58. Não são documentos fiscais válidos. Servem somente para exercitar geração e abertura de PDF.

`auditor_demo.xml` é o cenário sintético já existente de R$ 65.000,00 e NCM 87032100. Os testes não atestam assinatura, autorização ou enquadramento fiscal.

Os testes `test_auditor_original_*` reaproveitam os casos MIT do Auditor 1.2.2 com importações adaptadas; a licença integral está em `app/auditor_engine/LICENSE`.
