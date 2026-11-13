# Cadastros e consulta integral do XML

## Consulta no documento fiscal

O modal de escrituração oferece a guia **Dados do XML** e, em **Itens e tributos**, uma seção de consulta dos itens da origem. Emitente, destinatário, inscrições, endereço, autorização, transporte, cobrança, totalizadores, itens e os demais grupos são pesquisáveis por caminho XML ou valor. Os valores textuais, a precisão decimal declarada, atributos e grupos repetidos são preservados. Informação ausente não equivale a zero, isenção ou confirmação cadastral.

A árvore documental inclui o XML recebido, inclusive `infNFe`/`infCte`, protocolo, atributos e grupos que não alimentam cálculos. O protocolo integral permanece disponível; esta consulta não valida XSD, assinatura, autorização atual, enquadramento ou direito a crédito. A origem fica separada dos campos operacionais editáveis. Editar tributos da escrituração não modifica os valores originais exibidos.

Para documentos legados, a consulta procura o XML original nos pacotes retidos da própria empresa e exige correspondência do SHA-256 e da chave do documento. A recuperação é somente leitura: não reimporta documentos, não recalcula efeitos nem preenche cadastros silenciosamente. Original ausente ou incompatível gera aviso, mantendo disponíveis os campos já armazenados.

## Terceiros e inscrições

A identidade global mínima continua compartilhada por CPF ou raiz do CNPJ, com estabelecimentos identificados pelo CNPJ completo. Nomes, endereços, contatos, funções e inscrições continuam pertencendo ao cadastro local da empresa; não há ampliação de acesso entre empresas.

Novos participantes importados preservam os dados declarados disponíveis, inclusive complemento, país, CNAE, CRT, indicador de IE, SUFRAMA e IE de substituto. A IE e a UF presentes no XML alimentam a grade do estabelecimento com fonte identificada e atividade não informada. `ISENTO` ou o indicador explícito de isenção são evidência documental, não consulta cadastral atual. Ausência de IE não cria isenção. Dados anteriormente revisados não são sobrescritos.

A grade permite situação declarada, atividade independente, fonte e atualização informada pela fonte. O botão **Adicionar IE principal à grade** traz o dado já existente para revisão; somente salvar confirma a alteração.

## Produtos por empresa

O cadastro preserva seu escopo por empresa e a identidade do código do fornecedor por emitente. Produtos e serviços permanecem distintos. Foram disponibilizados CEST, EXTIPI, unidade/GTIN tributáveis, fabricante, benefício e ANP, além dos campos existentes.

**Consultar dados e XMLs** mostra os dados do cadastro e ocorrências documentais paginadas, com documento, item, chave, hash, valores, bases, alíquotas e impostos disponíveis. O XML completo pode ser consultado a partir de cada ocorrência. Preço, CFOP ou imposto de uma nota não vira regra automática nem substitui parâmetros revisados.

A consulta histórica exige simultaneamente leitura de cadastros e de documentos fiscais. Não usa documentos de outra empresa. A origem do cadastro é preservada durante a edição e alterações concorrentes continuam sujeitas ao controle de versão.

## Validação

- Testes de parser: repetição válida, rejeição de duplicação ambígua, precisão, atributos e ausência de IE.
- Testes de API: conservação dos tributos originais após edição operacional, recuperação legada somente por hash, ausência de mutação, imutabilidade da origem e isolamento de empresa/permissões.
- Testes do frontend: apresentação de folhas XML, grupos repetidos, zeros e campos explicitamente vazios.
- `scripts/browser_master_evidence.py`: instalação temporária com dados sintéticos, consulta no documento, IEs, histórico de produto e usuário somente leitura.

Não há migração destrutiva, preenchimento presumido, alteração automática em cadastros existentes ou mudança nos totais e classificações fiscais em razão desta interface.
