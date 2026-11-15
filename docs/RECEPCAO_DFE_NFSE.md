# Recepção DF-e / NFS-e: recuperação e primeiro incremento

Base: develop `3a6ab4c58f5c48aa0ea383cc2beeff615172ce71` (0.9.0-dev.9), conferida no remoto em 15/11/2026. Desenvolvimento em worktree exclusiva `escritura-reception-20261115`; sem merge, release, deploy ou mudança de banco operacional.

## Recuperação antes da implementação

- Inventário remoto de todos os 39 PRs e 45 branches: não havia PR publicado de recepção. PR35 (Docker), PR36/37 (SPED), PR38 (desempenho) e PR39 (contabilização de saídas) eram frentes abertas separadas. PR31/33 fornecem fundação e ensaio PostgreSQL, sem migração operacional nesta frente.
- `feat/integrations-postgres-validation`: zero commits exclusivos, 37 commits atrás de develop; comparação remota `behind`, merge-base `13216cfd132e36d6092cfbcc8240d64581c1c6c9`. Não continha a implementação relatada.
- `7716bb1`, `eee2f03`, `2884a51`, `9518cb9` e `1c78c76`: ausentes nos object databases dos 13 checkouts locais do projeto examinados e API GitHub respondeu 422, “No commit found for SHA”, para cada referência. Isso não prova inexistência em outro executor ou backup inacessível.
- Os cinco bundles `escritura-postgres-reception`, `escritura-nfse-procuracao`, `escritura-nsu-coordination`, `escritura-alphanumeric-local` e `escritura-integration-post-pr22-prepared` não estavam em `/workspace/shared`; nenhum foi portado. Os bundles de fundação/staging encontrados pertencem à frente PostgreSQL e não foram aplicados.
- Não há `AGENTS.md`, `.agents/skills` ou `SKILL.md` no checkout develop nem instruções ancestrais disponíveis. Foi lido o AGENTS de uma referência antiga `fiscal_intake_increment`, preservando as orientações aplicáveis de idioma, privacidade, develop e ausência de merge. `scripts/build.py check` e `pyproject.toml` ali mencionados não existem nesta base; os gates reais estão em `scripts/ci/checks.py` e `.github/workflows/ci.yml`.
- Foram consultadas também as automações existentes: já havia acompanhamento desta tarefa de recepção e das frentes Prosoft/contábil/SPED/Docker; nenhuma automação ou migração duplicada foi criada.
- Contexto pessoal estava indisponível; histórico visível do usuário e a delegação foram utilizados. Não se presume que tarefas de outras frentes tenham sido encerradas ou que relatos antigos de teste comprovem homologação real.

Os arquivos Library foram materializados no executor consumidor, tiveram identidade/atributos conferidos e foram lidos como ZIPs, sem executar seus programas:

| Referência | Bytes | SHA-256 |
|---|---:|---|
| ARGWS-Manifestador-1.1.1.zip | 13.277.254 | `ac08afe2c1ee9bf1b17f71d838662e1bef9a12dbd7388967bc0d1a03d4044317` |
| argws_crm_3.4.1.zip | 176.234.965 | `89411265c9fceb7b6cf7c8f0e7439d6eecd4314ac118d10476167f262eed18c3` |

Ambos passaram `ZipFile.testzip()`. Foram comparados `docs/CAPACIDADES_FISCAIS.md`, `docs/MANIFESTADOR_NFE_RECONSTRUCAO.md` e as rotinas Rust de distribuição/docZip do Manifestador. Seu fallback de GZip inválido para XML puro **não foi reproduzido**: a recepção exige GZip íntegro. A busca em arquivos de código/texto não vendor do CRM não encontrou `nfse.gov`, `cnpjConsulta`, `E2245`, `NFSeNacional` ou `nfse_nacional`; esse ZIP não comprovou um adaptador ADN recuperável. Arquivos externos e dados privados não entram no Git.

## Comportamento entregue

O upload existente `POST /api/companies/{cid}/imports/preview` aceita um arquivo `.xml` contendo `retDistDFeInt` 1.01 isolado ou dentro de SOAP 1.2, inclusive em ZIP suportado. Continua usando sessão, empresa ativa, exercício, CSRF, permissões, limites operacionais, armazenamento de originais, prévia, seleção e confirmação canônicos. Não há transporte externo, novo login ou nova base.

- `docZip` é base64/GZip estrito. Limites: resposta 20 MiB, até 50 pacotes por retorno, XML expandido 20 MiB, orçamento agregado 80 MiB e 1.000 membros compartilhado com compactados. Recusa GZip truncado, membros concatenados, bytes extras, entidades/DTD, NSU repetido/fora de intervalo, namespace/versão/ambiente incompatível e respostas com quantidade inconsistente. Campos não reconhecidos não viram documento fiscal.
- `procNFe_v4.00.xsd` com raiz `nfeProc` e modelo 55 segue ao leitor já existente: mesma verificação de empresa, emitente/destinatário, protocolo declarado e classificação fiscal. XSD, assinatura e autorização online continuam **não verificados**.
- `reception[]` guarda ambiente, status, NSUs informados e hashes por pacote, sem duplicar o XML em JSON. `summary`, `event` e `unsupported` ficam com motivo explícito e aviso na prévia. O envelope original conserva os bytes completos de todos os pacotes. Não há criação de documento para resumo/evento, ciência, manifestação, cancelamento ou mudança de estado a partir de evento recebido.
- Lote misto permite confirmar somente XMLs completos suportados. As pendências continuam no detalhe do lote após a confirmação. Lote só com resumo fica não confirmável, com a causa e original disponíveis. A política existente de retenção/limpeza continua aplicável aos originais; este incremento não cria um cofre de retenção permanente de pendências.
- `GET /api/companies/{cid}/imports/{id}/documents/{index}/download` recupera o XML íntegro por hash, byte a byte, com consulta e exportação fiscal exigidas novamente no serviço. Não aceita caminhos nem URLs. A extração canônica de originais também permite os fluxos existentes de evidência e DANFE para os XMLs recebidos.
- Emissão e escrituração permanecem campos separados. A opção existente `options.posting_date` e a revisão individual/parametrização existente por empresa continuam aplicáveis. Exemplo sintético: emissão 30/10, escrituração 06/11. Não se usa data de recepção/NSU para inferir competência.
- A nova confirmação de recepção verifica competência fiscal fechada dentro da mesma transação e exige reabertura, inclusive se a opção legada global `enforce_period_locks` estiver desativada. A prévia reavalia isso. Fluxos legados posteriores de edição/escrituração continuam com sua política existente; não houve refatoração global dessas opções nesta PR.
- Confirmação pendente não cria títulos ou lançamentos. Escrituração direta continua exigindo a preparação existente, CFOP/revisão e permissão própria. O original não é editado. A revisão do parser passa de 3 para 4 para não reutilizar uma prévia antiga que marcava o envelope como XML não suportado; a deduplicação de documentos continua canônica.

`app/reception.py` também fornece **construtores puros de requisição, sem execução HTTP**: `nfe_request` somente para `distNSU`; `adn_request` somente para GET `/DFe/{NSU}` com alvo explícito `cnpjConsulta` ou `cpfConsulta`, sem enviar os dois juntos. Endpoints/ambientes têm lista fixa e entradas não são interpoladas como XML. O formato remoto numérico não remove letras de CNPJ alfanumérico: esse caso é recusado até homologação específica. Isso não reduz a importação local alfanumérica já existente.

Para ADN, `adn_rejection` normaliza códigos documentados, sem persistir descrições potencialmente privadas. E2245 resulta em autorização pendente, mantém exatamente o cursor fornecido e nunca deduz procuração a partir de `TipoConsulta` de uma rejeição. Respostas de sucesso são explicitamente não suportadas por essa rotina. Ela ainda não está conectada a um transporte ou à UI.

## Matriz de cobertura real

“Testado” abaixo significa fixture sintética local, nunca consulta fiscal homologada.

| Documento / direção | Importação local atual | Consulta remota neste incremento | Ambientes do contrato / evidência |
|---|---|---|---|
| NF-e 55 recebida | XML 4.00 direto ou extraído de distribuição; prévia e confirmação testadas | Planejador distNSU, sem envio; entrega do XML depende do vínculo e regras SEFAZ | Produção e homologação separados; retornos sintéticos 1/2 testados |
| NF-e 55 emitida | XML de arquivo e direção por emitente testados; envelope sintético confirma extração | Distribuição não é promessa de recuperação dos XMLs gerados pelo próprio emitente; obter originais do emissor | Sem consulta real em nenhum ambiente |
| NFC-e 65 própria | Leitor de arquivo existente preservado por regressão | Não habilitada na recepção NF-e; pacote modelo 65 fica pendente/unsupported | Sem homologação de distribuição para 65 |
| NFC-e 65 recebida | Limites do leitor local existente e identificação do destinatário | Não implementada | Sem promessa de download por NSU |
| CT-e 57 emitido/recebido | Leitor de arquivo 4.00 existente; entrada exige tomador correto | Distribuição CT-e desabilitada/não implementada aqui | Contratos/ambientes próprios ainda precisam de desenvolvimento e homologação |
| MDF-e 58 | Sem importação fiscal completa neste núcleo | Desabilitada/não implementada | Não inferir cobertura a partir de NF-e ou existência de web service |
| NFS-e Nacional emitida/tomada/intermediada | Sem leitor de XML nacional integrado nesta PR | Planejador GET e rejeições puros; sem sucesso/recepção/transporte operacional | Produção e produção restrita separados; parâmetros/rejeições sintéticos testados |
| NFS-e municipal/outros documentos | Sem ampliação nesta PR | Não implementada | Não presumir que todos os municípios/documentos estão disponíveis no ADN |

## Fontes oficiais e limites da verificação

Consultadas em 15/11/2026:

1. [NT NF-e 2014.002 v1.40, julho/2026](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=uWO2d%2FgTuWg%3D): distribuição, atores, resumos, `distNSU`, janela e consumo indevido. A consulta pública indexada forneceu o conteúdo; abertura direta do PDF encontrou loop de redirecionamento neste ambiente. Não se usa a versão 1.02 antiga como contrato atual. XML próprio do emitente não é garantido pela distribuição; resumo não autoriza criar manifestação para liberar XML.
2. [Documentação atual NFS-e, atualizada em 04/11/2026](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual) e [manual de contribuintes ADN v1.1, 03/11/2026](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-municipios-apis-adn-sistema-nacional-nfs-e-v1-1-20261103.pdf): atores, CNPJ base, alvo por CNPJ/CPF, procuração, `TipoConsulta`, E2244/E2245 e demais rejeições. O nome do arquivo contém “municipios”, mas a capa e o conteúdo são o Manual dos Contribuintes.
3. [Relação oficial de APIs de produção/produção restrita](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao): endpoints distintos dos contribuintes. A leitura pública do Swagger e de sua especificação na produção restrita retornou **HTTP 503** neste executor, sem uso de certificado. Não foi inferido um JSON de sucesso.

As dicas de cooldown NF-e (137, 656 ou fim do lote → 3.600 s) são metadados para o futuro coordenador, **não um agendador operacional**. `cursor_advance_allowed=false` permanece sempre falso: nenhum NSU é persistido/avançado. O recebimento de um envelope enviado pelo operador não prova que ele foi consultado remotamente em nome da empresa; XMLs completos ainda são conferidos contra o cadastro ativo, e resumos/eventos não produzem movimentos.

## Próximos incrementos e dependências

1. Cofre A1 por empresa com configuração local segura e referência sem segredo em logs/chat; validar titular, validade/cadeia, ambiente, autorização/mesma base/procuração. Não solicitar PFX, senha ou chave no chat. Nenhum certificado foi usado nesta entrega.
2. Transporte autenticado somente para consulta; fixtures oficiais/Swagger ADN e leitor nacional de XML, tratamento de sucesso, preservação e download. Testes separados com autorização por empresa em produção restrita/homologação e produção.
3. Fila/agendamento manual/automático reutilizando os mesmos serviços e permissões; lease exclusivo por inscrição/provedor/ambiente, cooldown compartilhado entre operadores e instâncias, cursor salvo atomicamente somente após persistência íntegra de **todos** os pacotes e preservado em falha/E2245. Deduplicar resumo → XML sem sobrescrever origem e expor fila de pendências na UI.
4. Política explícita de competência/revisão por empresa para a recepção automática; jamais confundir emissão, chegada e escrituração. Ampliação CT-e/MDF-e/NFC-e somente mediante seus protocolos/fontes e testes próprios.
5. PostgreSQL operacional depende de adoção validada da frente própria; esta PR mantém SQLite nos binários e no núcleo atual. Sem migração duplicada, Redis/MinIO decorativos ou implantação de Atlas.

## Validação

Resultados locais: **310 testes de backend passaram em 122,203 s**, incluindo 19 novos; após o reforço final do orçamento esgotado de descompressão, os 19 novos passaram novamente em 2,975 s. **138 testes de frontend passaram** e o build Vite foi concluído em 3,48 s, com o aviso preexistente de chunk acima de 500 kB. Sintaxe dos oito arquivos Python alterados/novos e `git diff --check` aprovados. Não há workflow alterado nem actionlint disponível no executor.

A primeira rodada ampla retornou um nome de módulo inexistente no comando (`test_import_scope`) e dependências py7zr/rarfile ausentes; o comando foi corrigido e as versões já exigidas pelo projeto instaladas somente em `/tmp/escritura-reception-deps`, antes da rodada aprovada. Nenhuma dependência da aplicação foi alterada. O build reutilizou dependências frontend cujo lockfile tinha SHA-256 idêntico ao deste checkout.

Comando da rodada ampla aprovada:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-reception-deps:/tmp/escritura-daily-test-deps:tests:. python3 -m unittest test_reception test_importers test_fiscal_import test_import_revision test_import_reprocessing test_import_payables test_import_masters test_import_package_cleanup test_master_evidence test_operational_settings test_evolution test_core test_xml_billing_parser test_importer_movement_dates test_archives test_archive_pdf_accessories test_business test_management test_bulk_security test_reprocessing_linked_effects test_generated_payables -q
```

Suíte nova: `PYTHONPATH=/tmp/escritura-daily-test-deps:tests:. python3 -m unittest test_reception -v`; usa somente fixtures e bancos temporários. Regressões abrangem leitores, importação, CFOP/datas, financeiro, reprocessamento, originais, permissões, auditoria e limpeza. A dependência DANFE já exigida pelo projeto foi reutilizada de um diretório isolado, sem alteração dos requisitos.

Não foram executados consulta remota com certificado, homologação SEFAZ/ADN, PVA/Prosoft, dados reais, instaladores nativos ou imagem operacional. Builds e CI devem ser informados pelo resultado efetivo, separadamente dos testes sintéticos locais.
