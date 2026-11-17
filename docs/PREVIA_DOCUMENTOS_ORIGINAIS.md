# Prévia do XML original na escrituração

Incremento local sobre `develop` 67a5e2e0b3c65fe7948827d6d66da5361970bfb1 (0.9.0-dev.23), verificado em 16/11/2026. Não altera a escrituração, datas, valores, títulos, partidas ou XMLs. Sem transmissão, consulta SEFAZ ou conversão manual.

## Inventário e limites

| Origem | Renderizador já existente | Situação neste incremento |
| --- | --- | --- |
| NF-e 55, XML 4.00 | BrazilFiscalReport 1.3.1 / DanfeMoc70 | Prévia na escrituração; amostras sintéticas A4 de 1 e 3 páginas inspecionadas, 80 itens preservados. |
| NFC-e 65, XML 4.00 | BrazilFiscalReport 1.3.1 / Danfce | Prévia na escrituração; bobina sintética inspecionada, QR decodificado para o valor original `example.invalid`, sem navegar. |
| CT-e 57, XML 4.00 | BrazilFiscalReport 1.3.1 / Dacte | Composição medida para CT-e normal rodoviário, retrato, emissão e serviço normais. Demais perfis e grupos especiais são recusados explicitamente; não há fallback para o layout com cortes. Ver validação atual abaixo. |
| MDF-e 58, XML 3.00 | BrazilFiscalReport 1.3.1 / Damdfe, já usado na auditoria | Não integrado à escrituração: o importador fiscal não aceita esse leiaute. Não se cria documento fiscal para habilitar a prévia. |
| CT-e OS 67 | Espelho próprio de conferência na auditoria | Não equivale a DACTE OS; recusado nesta prévia de leiaute. |
| NFS-e | `Danfse` existe na dependência 1.3.1 | Não integrado ao fluxo fiscal/registro e não validado contra NT 008/2026; perfis municipais/nacional e vínculo ao XML exigem trabalho específico. Recepção ADN não implica renderização/escrituração. |
| CC-e/eventos | `DaCCe` existe na dependência | Evento não equivale a nota escriturada; pendente de integração específica. |
| NFCom, NF3e, BP-e, outros | Sem perfil validado neste fluxo | Mensagem explícita de modelo não suportado, sem inventar representação oficial. |

A reprodução parte do XML, não do PDF personalizado originalmente emitido pelo fornecedor. Não certifica assinatura, XSD, autorização, enquadramento fiscal, totalizadores ou atendimento integral às NTs/RTC. A existência do renderizador não homologa todos os modais/contingências. Não removemos marcas de homologação nem encurtamos o XML para esconder problemas de layout.

## Uso e segurança

Em **Escrituração e documentos**, `Visualizar original` abre o documento auxiliar. Também disponível dentro da consulta/edição. A janela identifica empresa, número e competência, oferece página anterior/próxima e zoom, fecha por botão/Esc e devolve o foco. O editor permanece intacto ao fechar a prévia. Troca de empresa, competência, módulo, sessão ou desativação da aba fecha a consulta.

`GET /api/companies/{cid}/documents/{id}/auxiliary` exige `fiscal.documents:read` e `export` (o PDF pode ser salvo pelo cliente); não amplia permissões de importação. Seleciona exclusivamente a empresa/ID pedidos e recupera o hash original primário, conferindo SHA-256 dos bytes, chave, modelo, namespace e versão. Não escolhe outra versão só porque possui a mesma chave. ZIPs usam o leitor limitado existente; nomes iguais em pastas diferentes não determinam a seleção. Ausência/corrupção/modelo não suportado produzem diagnóstico, nunca PDF reconstituído dos campos editados.

As respostas têm `Cache-Control: no-store`, identificação do renderizador e hash. Não há cache persistente de PDFs nem gravação fiscal. O lookup de originais reutiliza a busca por hash no JSON de importação; desempenho em bases grandes ainda requer medição, fora desta amostra.

PDF.js 6.5.438, build `legacy`, e codecs JS locais são carregados somente ao abrir a prévia. `npm run build`/`npm run dev` preparam os codecs. Não há CDN, navegação de QR, `eval` nem relaxamento de CSP. Renderização de uma página por vez a 2x, cancelamento de fetch/render e contadores de geração impedem respostas antigas de ocupar a seleção atual. A build normal do PDF.js usou API JS ainda ausente no Chromium 141 do ambiente; por isso foi adotada a build oficial de compatibilidade.

## Evidências da versão inicial (histórico) e reprodução

- Backend: 64 testes passaram (`test_document_preview`, `test_import_revision`, `test_master_evidence`, `test_core`, `test_evolution`). As 6 provas novas cobrem modelos reais, bytes exatos em ZIP com basenames repetidos, edição independente, repetição sem writes, origem ausente/alterada/inválida, modelo não suportado, acesso por empresa e read/export, DANFE multipágina.
- Frontend: 181 testes Node passaram; build Vite passou. Aviso de chunk principal acima de 500 kB permanece; PDF.js é chunk separado sob demanda.
- Chromium headless local: abrir/fechar, Esc/foco, zoom, página 2, editor sem gravação, falha/retry, resposta atrasada, troca de empresa e imutabilidade de documentos/títulos/partidas passaram. O HTTP 422 registrado no console é a falha sintética deliberada; não houve `pageerror`.
- PDFs: inspeção visual e extração de texto não substituem homologação. DANFE de 80 itens gera 3 páginas e contém todos os itens. A verificação opcional de códigos diferencia PDF em alta resolução dos pixels do canvas. A fixture DACTE tem QR parcialmente coberto por marca de homologação: a leitura exata foi confirmada no canvas a 2x, mas não no raster do PDF a 4x. Barras dos DANFEs de 1/3 páginas e QR NFC-e coincidiram com o XML tanto no PDF quanto no canvas. Essa diferença de leitura e a sobreposição de textos mantêm o DACTE pendente de revisão visual. Chaves artificiais compostas quase só por noves também reproduziram leitura Code128 de 42 em vez de 44 dígitos, inclusive diretamente em python-barcode 0.16.1; a evidência foi mantida em `codes-all-nines.json`/`all-nines-*.pdf`. Chaves estruturadas com CNPJ zero continuam sintéticas e permitem comparar a leitura exata nos DANFEs.
- Ambiente: Python 3.12.14, SQLite temporário, BrazilFiscalReport 1.3.1. O Python compartilhado não tinha o renderizador; foi usado o venv já isolado da tarefa de trânsito somente como runtime, sem modificá-lo. `/tmp` ficou cheio por uso do ambiente; os testes passaram a usar `artifacts/tmp`, sem limpar arquivos de outras frentes. Chromium do sistema falhou por restrição de socket; usado headless shell 141 disponível no ambiente.
- Não executados: UI desktop Qt empacotada, suite backend completa, CI remota antes da publicação do rascunho, produção, certificados ou transmissão.

Com dependências do repositório instaladas em um venv:

```bash
PYTHONPATH=.:tests python -m unittest test_document_preview test_import_revision test_master_evidence test_core test_evolution -v
node --test frontend/tests/*.test.js
npm run build --prefix frontend
mkdir -p artifacts/tmp
TMPDIR="$PWD/artifacts/tmp" ESCRITURA_TEST_BROWSER=/caminho/headless_shell PYTHONPATH=. python scripts/browser_document_preview.py
# QA opcional: PyMuPDF, Pillow e zxing-cpp, instalados apenas no ambiente de teste.
python scripts/check_document_preview_pdfs.py
```

O script do navegador usa banco descartável, fixtures `auditor_*` existentes e chaves/CNPJ fictícios. Emite `artifacts/document-preview/report.json`, PDFs, XMLs derivados, screenshots da aplicação e pixels completos dos canvases. O verificador de PDF salva `pdf-qa.json` com resultados inclusive negativos e PNGs de todas as páginas para inspeção. Esses artefatos não são adicionados ao código nem publicados com dados reais.

## Referências consultadas em 16/11/2026

- [Portal NF-e: MOC 7.0, Anexo II DANFE e manual NFC-e/QR v6.0](https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=ndIjl+iEFdE%3D).
- [CONFAZ: MOC 7, Anexo II, DANFE e código de barras](https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais/moc7-anexo-ii-manual-especificacoes-tecnicas-danfe-codigo-barras.pdf/view).
- [DANFE NFC-e/QR, versão 6.0, março/2025; QR 2.00 e 3.00](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=k%2FIuuaW4YiY%3D).
- [Portal CT-e: MOC 4.00, Anexo II DACTE, agosto/2022](https://www.cte.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=yIxPYTwmPQM%3D), inclui modelos de DACTE OS e requisitos de QR/código de barras. Não equivale a afirmar conformidade integral da biblioteca.
- [Portal MDF-e: MOC 3.00b, Anexo II DAMDFE](https://dfe-portal.svrs.rs.gov.br/Mdfe/Documentos).
- [Portal NFS-e: NT 008/2026, padrão DANFSe](https://www.gov.br/nfse/pt-br/noticias/se-cgnfs-e-publica-nota-tecnica-no-008-2026-com-regras-para-emissao-do-danfse).
- [BrazilFiscalReport, projeto oficial](https://github.com/Engenere/BrazilFiscalReport); a versão utilizada continua fixada em 1.3.1, sem atualizar para a versão mais recente do projeto.
- [PDF.js: uso de worker, renderização e paginação](https://mozilla.github.io/pdf.js/examples/). Licenças das dependências e codecs preservadas no build.


## Histórico d3997a2b: correção parcial de QR, layout então reprovado

Correção local `PreviewDacte` sobre BrazilFiscalReport 1.3.1: redesenha apenas o QR e sua área branca depois da marca d'água, com margem de pelo menos 10% da dimensão total e conteúdo extraído do XML. Preserva a marca diagonal e acrescenta identificação explícita de homologação no espaço variável do cabeçalho. Restaura a posição de desenho, sem alterar bytes XML, dados fiscais ou dependência instalada. Aplica-se também aos cabeçalhos de continuação. Referência: MOC CT-e 4.00 Anexo II §§2.18, 2.20 e 2.21.1 (link acima); marca d'água não pode impedir leitura. Não é certificação do leiaute.

Causas ainda **não corrigidas**: `_draw_recipient_sender`/`_draw_service_recipient` usam `multi_cell(w=0)` com alturas e posições fixas; logradouro/bairro/município atravessam outras colunas. `limit_text` e `long_field` cortam nomes na biblioteca; a altura do endereço do emitente também desloca o título DACTE. Uma correção completa exige medir quebras e redistribuir/paginar os quadros sem omitir campos. Não foi substituído por espelho inventado nem reduzido o XML para disfarçar esses defeitos. O aviso da interface os identifica expressamente. Esta continuação **não conclui** a exigência de fidelidade de textos longos.

Evidência final local: 65 testes backend, 181 frontend e build passaram; navegador passou com abertura/fechamento, troca de empresa/seleção, zoom e continuação DACTE. `auditor_cte_long` deriva exclusivamente da fixture sintética: nomes/endereço ampliados, 30 documentos originários, URL de teste com parâmetros XML escapados, homologação. PDFs/XMLs/canvases permanecem em `artifacts/document-preview`; falhas anteriores em `artifacts/dacte-before-qr-fix`. Nenhum endereço QR é acessado.

O QR dos dois DACTEs coincide exatamente com o conteúdo XML no PDF rasterizado a 1,25x/2x/4x e no canvas a 75/100/125/150%. Entretanto, Code128 não decodifica nas rasterizações 1,25x/2x nem no canvas 75%; decodifica a 4x e no canvas 100/125/150%. **O comando `scripts/check_document_preview_pdfs.py` retorna falha**, pois conserva a exigência de leitura de todos os códigos em todos esses tamanhos. Os resultados negativos e `layout_status: FAIL` permanecem em `pdf-qa.json`; não foram transformados em sucesso. A inspeção visual confirma sobreposições/cortes, embora o QR e a identificação de homologação estejam legíveis. Não interpretar testes funcionais aprovados como aceite visual integral.


## Revisão atual: composição medida e matriz de códigos aprovada localmente

`PreviewDacte` mantém o leitor XML do BrazilFiscalReport 1.3.1 e substitui os quadros afetados por largura delimitada e altura calculada antes do desenho. Nomes, logradouros, complementos, municípios, componentes e observações não passam por `limit_text`/`long_field`. As células crescem ou continuam na folha seguinte com as mesmas colunas. Observações que cabem numa folha ficam inteiras; títulos acompanham a primeira linha. O título DACTE tem posição independente da altura do endereço do emitente. Todas as folhas repetem identificação completa, chave, códigos, natureza, protocolo, numeração atual/total e identificação de homologação. Campos ausentes não são convertidos em zeros inventados.

A marca diagonal opcional foi substituída pela identificação obrigatória centralizada, em caixa alta, no cabeçalho de todas as folhas. O manual permite marca d'água apenas se não afetar a leitura; mantê-la sobre textos e códigos contrariava essa condição. Isso não muda `tpAmb`, autorização, assinatura ou qualquer byte XML.

O código anterior era comprimido em 8,5 mm de altura; agora o Code128-C tem 15 mm, início C explícito, pares dos 44 dígitos, checksum módulo 103 e dez módulos de silêncio em cada lado. Símbolos vetoriais não dependem de bitmap de baixa resolução. O principal usa módulo 25,4/90 mm (largura total 83,82 mm). O rodapé repete a mesma chave com módulo 25,4/96 mm (78,58125 mm); essa repetição é permitida pelo §2.21.3 e evita que a mesma fase de rasterização afete ambos. A leitura nas menores escalas pode vir do símbolo do rodapé: não se afirma que cada símbolo isolado sempre decodifique. Ambos respeitam o limite de largura e a altura/margens do MOC. Impressão física continua sujeita à resolução mínima de 300 dpi do manual; aprovação de screenshots não é garantia para qualquer dispositivo ou chave.

Escopo explícito: modelo 57 normal, rodoviário, retrato, emissão normal e serviço normal. Outros modais, contingência, tipos de CT-e/serviço e grupos especiais (perigosos, veículos novos, globalizado e multimodal) retornam `renderer_not_validated`. Não há espelho genérico fingindo um DACTE suportado. A adaptação é selecionada apenas pelo endpoint de prévia da escrituração; a auditoria e os demais modelos continuam usando seus renderizadores anteriores. Formulários com dados de emitente que excedam a capacidade segura do cabeçalho retornam erro explícito, nunca corte silencioso. Isso é um limite de suporte, não certificação de conformidade integral.

Validação final local:

- 67 testes backend; 181 testes frontend; build Vite; cenário Chromium completos aprovados. O aviso de chunk grande permanece; o único HTTP 422 do navegador é intencional no teste de falha/retry. Não há `pageerror`.
- DACTEs sintéticos de 2, 3 e 8 páginas: campos longos distintos, CPF de tomador, expedidor/recebedor, 30 e 120 referências e 30 observações extensas. Campos completos, todas as referências e marcadores finais aparecem no PDF; estado fiscal/hash/XML permanecem idênticos. A amostra longa passou de 2 para 3 páginas para preservar campos e divisórias, sem reduzir fonte para forçar a contagem anterior.
- A matriz original permanece: PDF 1,25x/2x/4x; canvas 75/100/125/150%. Foi ampliada a todas as páginas dos três DACTEs: 39 rasterizações PDF e 52 canvases, totalizando 91 combinações. Os canvases comparados são seus pixels internos a 2x, não uma garantia de leitura óptica de screenshots CSS reduzidos ou de qualquer tela/câmera. QR e Code128 coincidem com XML/chave. O comando QA agora termina com sucesso, sem remover as assertivas anteriores.
- Acrescentadas verificações de conteúdo completo, texto dentro dos quadros e colisões na mesma linha. O relatório atual contém listas vazias de campos ausentes, colisões e saídas dos quadros. A inspeção humana percorreu todas as páginas e canvases de continuação; não equivale a homologação fiscal.
- Evidências negativas anteriores continuam preservadas em `artifacts/dacte-before-qr-fix` e `artifacts/dacte-before-layout-fix`; resultados atuais, PDFs, XMLs e pixels em `artifacts/document-preview`. Nenhuma falha histórica foi apresentada como aprovação.

Referências específicas: MOC CT-e 4.00 Anexo II §§2.3, 2.6, 2.8 e 2.12 (campos/quebras/continuações), §2.17 (Code128-C, margens, altura e resolução), §§2.18/2.20/2.21.1 (QR, homologação e marca d'água), §2.21.3 (código adicional no rodapé), conforme fonte oficial já vinculada acima. A versão da dependência permanece fixada; não há alteração da instalação compartilhada, XML de origem, escrituração ou transmissão.


## Controles da caixa de prévia

A barra reúne páginas, zoom, **Ampliar / Restaurar**, **Baixar PDF** e **Imprimir PDF**. Ampliar ocupa a área disponível do navegador sem abrir uma segunda janela ou alterar a escala do documento; restaurar mantém página e zoom. Em telas estreitas, os controles quebram em linhas e a rolagem fica dentro do documento, preservando as proporções.

Download e impressão usam um Blob privado dos mesmos bytes recebidos pela prévia, antes de o PDF.js transferir o buffer. Não repetem a chamada fiscal nem regeneram o PDF. A impressão usa o leitor PDF do navegador, preservando páginas e tamanho do PDF, não uma captura do canvas. Se esse leitor não estiver disponível, houver falha ou demora na abertura, a caixa orienta baixar e imprimir em um leitor externo. O resultado físico depende do leitor, configuração e impressora; não há homologação de impressão física.

Fechar, trocar documento/contexto ou repetir a carga cancela a preparação de impressão, remove o iframe privado e revoga o Blob. ESC e foco continuam sob BaseModal; não há mudanças em ReportPdfPreview.vue nem na persistência de guias. A imagem de referência real não integra o repositório ou as fixtures.

Reprodução sintética: testes Node de document-preview (bytes, falha, cancelamento e revogação), `scripts/browser_document_preview.py` (grid/editor, ampliar/restaurar, PDF baixado idêntico à resposta, impressão ou diagnóstico conforme capacidade real, móvel, Esc/foco, erro/retry e contexto). O cenário roda também na CI com Chromium completo. Resultados efetivos e limites do ambiente são registrados na PR.
