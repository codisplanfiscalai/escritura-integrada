# Carga CFOP dos relatórios enviados

`app/data/cfop-carga-tabcfop-20261109.json` é a carga padrão importável. Preserva os registros das extrações integrais de `tabcfop.pdf` e `tabcfop.txt`, sem converter códigos de três dígitos nem ativar parâmetros como regras tributárias.

## Cobertura conferida

| Verificação | Resultado |
| --- | ---: |
| Páginas PDF na extração | 158, contínuas |
| Registros em cada fonte | 779 |
| Códigos distintos / duplicados | 779 / 0 |
| Códigos com três / quatro dígitos | 228 / 551 |
| Coincidem com o CONFAZ em 09/11/2026 | 539 |
| Quatro dígitos sem correspondência | 12 |
| CFOPs oficiais ausentes nos anexos | 80 |
| Campos declarados preservados | 6.232, oito por registro |
| Ocorrências de alíquotas, na ordem da origem | 4.002 |
| Registros sem alíquotas informadas | 13 |
| Descrições diferentes entre PDF e TXT | 735 |

Os conjuntos de códigos, as listas de alíquotas e os três indicadores conferidos coincidem nos 779 registros. A descrição do PDF é usada na apresentação; a do TXT também é preservada. Os textos completos das duas extrações estão no JSON, com hashes e intervalos de linhas por registro, sem corrigir sua acentuação.

Os 12 códigos sem correspondência são 1991, 1999, 2991, 2999, 3991, 3999, 5991, 5999, 6991, 6999, 7991 e 7999. A ausência na referência consultada não prova sua situação em todos os períodos históricos. Os 228 códigos de três dígitos ficam como legados da origem, sem associação presumida com códigos atuais.

## Campos da carga

| Campo JSON | Informação preservada |
| --- | --- |
| `code` | Código exato da origem, como texto |
| `source_description`, `txt_description` | Descrições das duas fontes |
| `parameters_declared.revenue` | Faturamento |
| `revenue_tax_base`, `revenue_exempt`, `revenue_other` | Composição do faturamento nas colunas base de cálculo, isentas e outras de IPI/ICMS, inclusive `+`, `-` e `Não Entra` |
| `icms_declared`, `ipi_declared`, `gi_declared` | Indicadores da origem, sem afirmar incidência legal |
| `me_epp_purchases` | Enquadramento da base ME/EPP por compras |
| `rates_declared` | Valores com quatro casas e ordem preservada; lista vazia significa não informado |
| `valid_from`, `valid_to` | Vazios: a origem não informou vigência dos parâmetros |
| `review_status` | `unreviewed` |
| `source_spans`, `source_texts`, `extracted_text_sha256`, `sources` | Localização, extrações integrais e identificação das fontes |

A emissão de 09/11/2026 está identificada no PDF, sem ser transformada em início de vigência. O cabeçalho do TXT tem data incompleta; sua emissão permanece não informada. As vigências da redação CONFAZ pertencem à referência oficial, não aos parâmetros desses relatórios.

## Uso e preservação

Ative a empresa e abra Fiscal → CFOP e associações → **Carga de referência**. Use a carga padrão ou selecione um JSON `escritura-cfop-source/1`, confira os dados e escolha **Importar carga na empresa**, informando o motivo.

A operação completa a tabela com os códigos da referência oficial elegíveis na data escolhida, preservando cadastros existentes. Em novembro de 2026 são 619 CFOPs. Todos os 779 registros dos anexos ficam preservados separadamente na empresa, inclusive os 240 sem correspondência atual, e podem ser consultados e baixados integralmente. Os 80 códigos oficiais ausentes nos anexos continuam disponíveis pela fonte CONFAZ.

Repetir a mesma carga não duplica nem sobrescreve registros. A gravação é transacional e auditada, com isolamento por empresa e controle de permissões. Os parâmetros ficam inativos e não participam do motor tributário, das associações ou dos movimentos. Sua homologação para uso automático exige vigência, contexto e revisão específicos, fora desta conversão.

## Reprodução, testes e limites

`scripts/convert_cfop_report.py` recebe as duas extrações UTF-8 completas e metadados, produzindo JSON importável, CSV de conferência e JSON de comparação. Recusa códigos repetidos, conjuntos diferentes, campos ausentes, divergência de indicadores/alíquotas e páginas PDF descontínuas. A aplicação reconstrói os registros a partir dos textos antes de aceitar a carga, recusando alterações inconsistentes.

Os originais foram identificados na Biblioteca, mas a transferência de seus bytes falhou nesta execução. A leitura textual foi concluída até o fim de ambos. O pedido de imagem PDF retornou apenas uma referência, sem pixels acessíveis. Portanto não houve inspeção visual do PDF nem hash dos arquivos originais. Os hashes identificam as **extrações textuais**; os metadados registram `original_bytes_verified=false` e `pixels_verified=false`.

`tests/test_cfop_source.py` cobre reconstrução, quantidades, origem, isolamento, permissões, idempotência, ausência de ativação e preservação dos cadastros. O fluxo Chromium importa o JSON e consulta parâmetros e códigos legados. Os smokes de Windows/macOS/Docker conferem a presença dos 779 registros no pacote. Resultados devem ser associados ao commit testado; a aprovação do incremento anterior não substitui os novos gates.
