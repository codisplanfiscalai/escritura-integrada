# Prévia do XML original na escrituração

Incremento local sobre `develop` 67a5e2e0b3c65fe7948827d6d66da5361970bfb1 (0.9.0-dev.23), verificado em 16/11/2026. Não altera a escrituração, datas, valores, títulos, partidas ou XMLs. Sem transmissão, consulta SEFAZ ou conversão manual.

## Inventário e limites

| Origem | Renderizador já existente | Situação neste incremento |
| --- | --- | --- |
| NF-e 55, XML 4.00 | BrazilFiscalReport 1.3.1 / DanfeMoc70 | Prévia na escrituração; amostras sintéticas A4 de 1 e 3 páginas inspecionadas, 80 itens preservados. |
| NFC-e 65, XML 4.00 | BrazilFiscalReport 1.3.1 / Danfce | Prévia na escrituração; bobina sintética inspecionada, QR decodificado para o valor original `example.invalid`, sem navegar. |
| CT-e 57, XML 4.00 | BrazilFiscalReport 1.3.1 / Dacte | Prévia implementada e testada, mas fidelidade visual ainda pendente: textos longos sobrepostos nos quadros de partes/tomador e QR sob marca de homologação na fixture rodoviária. Aviso explícito na prévia. |
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

## Evidências locais e reprodução

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
