# Recepção DF-e / NFS-e: consulta mTLS e importação revisada

Base inicial dev.9 `3a6ab4c`; atualização sincronizada com develop dev.10 `6344584593f3a64126ef69095b7645760b716095`, preservando a PR38; dev.11 `21b6e76` incorporou a PR36 e a continuação usa dev.12 `955404e`, preservando a PR35 sem executar migração. Desenvolvimento em worktree exclusiva `escritura-reception-20261115`. A PR41 continua draft, sem integração em develop/main, release, deploy ou mudança de banco operacional. A recepção manual de arquivo e o transporte mTLS fazem parte da mesma PR; nenhuma consulta fiscal externa foi executada nesta validação.

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

O upload existente `POST /api/companies/{cid}/imports/preview` aceita um arquivo `.xml` contendo `retDistDFeInt` 1.01 isolado ou dentro de SOAP 1.2, inclusive em ZIP suportado. Continua usando sessão, empresa ativa, exercício, CSRF, permissões, limites operacionais, armazenamento de originais, prévia, seleção e confirmação canônicos. O transporte manual mTLS descrito abaixo acrescenta a consulta; o upload existente continua independente da rede, sem novo login ou nova base.

- `docZip` é base64/GZip estrito. Limites: resposta 20 MiB, até 50 pacotes por retorno, XML expandido 20 MiB, orçamento agregado 80 MiB e 1.000 membros compartilhado com compactados. Recusa GZip truncado, membros concatenados, bytes extras, entidades/DTD, NSU repetido/fora de intervalo, namespace/versão/ambiente incompatível e respostas com quantidade inconsistente. Campos não reconhecidos não viram documento fiscal.
- `procNFe_v4.00.xsd` com raiz `nfeProc` e modelo 55 segue ao leitor já existente: mesma verificação de empresa, emitente/destinatário, protocolo declarado e classificação fiscal. XSD, assinatura e autorização online continuam **não verificados**.
- `reception[]` guarda ambiente, status, NSUs informados e hashes por pacote, sem duplicar o XML em JSON. `summary`, `event` e `unsupported` ficam com motivo explícito e aviso na prévia. O envelope original conserva os bytes completos de todos os pacotes. Não há criação de documento para resumo/evento, ciência, manifestação, cancelamento ou mudança de estado a partir de evento recebido.
- Lote misto permite confirmar somente XMLs completos suportados. As pendências continuam no detalhe do lote após a confirmação. Lote só com resumo fica não confirmável, com a causa e original disponíveis. A política existente de retenção/limpeza continua aplicável aos originais; este incremento não cria um cofre de retenção permanente de pendências.
- `GET /api/companies/{cid}/imports/{id}/documents/{index}/download` recupera o XML íntegro por hash, byte a byte, com consulta e exportação fiscal exigidas novamente no serviço. Não aceita caminhos nem URLs. A extração canônica de originais também permite os fluxos existentes de evidência e DANFE para os XMLs recebidos.
- Emissão e escrituração permanecem campos separados. A opção existente `options.posting_date` e a revisão individual/parametrização existente por empresa continuam aplicáveis. Exemplo sintético: emissão 30/10, escrituração 06/11. Não se usa data de recepção/NSU para inferir competência.
- A nova confirmação de recepção verifica competência fiscal fechada dentro da mesma transação e exige reabertura, inclusive se a opção legada global `enforce_period_locks` estiver desativada. A prévia reavalia isso. Fluxos legados posteriores de edição/escrituração continuam com sua política existente; não houve refatoração global dessas opções nesta PR.
- Confirmação pendente não cria títulos ou lançamentos. Escrituração direta continua exigindo a preparação existente, CFOP/revisão e permissão própria. O original não é editado. A revisão do parser passa de 3 para 4 para não reutilizar uma prévia antiga que marcava o envelope como XML não suportado; a deduplicação de documentos continua canônica.

`app/reception.py` também fornece **construtores puros de requisição, sem execução HTTP**: `nfe_request` somente para `distNSU`; `adn_request` somente para GET `/DFe/{NSU}` com alvo explícito `cnpjConsulta` ou `cpfConsulta`, sem enviar os dois juntos. Endpoints/ambientes têm lista fixa e entradas não são interpoladas como XML. O formato remoto numérico não remove letras de CNPJ alfanumérico: esse caso é recusado até homologação específica. Isso não reduz a importação local alfanumérica já existente.

Para ADN, `adn_rejection` normaliza códigos documentados, sem persistir descrições potencialmente privadas. E2245 resulta em autorização pendente, mantém exatamente o cursor fornecido e nunca deduz procuração a partir de `TipoConsulta` de uma rejeição. O serviço de captura usa essa rotina após o transporte. O perfil JSON de sucesso recuperado abaixo permite extrair XMLs e avançar NSU após persistência integral; formatos diferentes permanecem opacos, sem avanço. Não há UI nova de configuração/consulta.

## Matriz de cobertura real

“Testado” abaixo significa fixture sintética local, nunca consulta fiscal homologada.

| Documento / direção | Importação local atual | Consulta remota neste incremento | Ambientes do contrato / evidência |
|---|---|---|---|
| NF-e 55 recebida | XML 4.00 direto ou extraído de distribuição; prévia e confirmação testadas | Cliente distNSU mTLS de uma página; captura e cursor transacional, com encaminhamento explícito à prévia. XML depende de vínculo/regras SEFAZ | Produção e homologação separados; retornos sintéticos 1/2 testados |
| NF-e 55 emitida | XML de arquivo e direção por emitente testados; envelope sintético confirma extração | Distribuição não é promessa de recuperação dos XMLs gerados pelo próprio emitente; obter originais do emissor | Sem consulta real em nenhum ambiente |
| NFC-e 65 própria | Leitor de arquivo existente preservado por regressão | Não habilitada na recepção NF-e; pacote modelo 65 fica pendente/unsupported | Sem homologação de distribuição para 65 |
| NFC-e 65 recebida | Limites do leitor local existente e identificação do destinatário | Não implementada | Sem promessa de download por NSU |
| CT-e 57 emitido/recebido | Leitor de arquivo 4.00 existente; entrada exige tomador correto | Distribuição CT-e desabilitada/não implementada aqui | Contratos/ambientes próprios ainda precisam de desenvolvimento e homologação |
| MDF-e 58 | Sem importação fiscal completa neste núcleo | Desabilitada/não implementada | Não inferir cobertura a partir de NF-e ou existência de web service |
| NFS-e Nacional emitida/tomada/intermediada | Recepção de pacotes XML; leitor de escrituração nacional pendente | GET mTLS, JSON/ArquivoXml GZip/base64, origem e XMLs individuais; avanço transacional somente para perfil reconhecido completo | Produção e produção restrita separados; titulares/matriz/filial/procuração testados com fixtures do contrato recuperado. Sem consulta/homologação externa |
| NFS-e municipal/outros documentos | Sem ampliação nesta PR | Não implementada | Não presumir que todos os municípios/documentos estão disponíveis no ADN |

## Fontes oficiais e limites da verificação

Consultadas em 15/11/2026:

1. [NT NF-e 2014.002 v1.40, julho/2026](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=uWO2d%2FgTuWg%3D): distribuição, atores, resumos, `distNSU`, janela e consumo indevido. A consulta pública indexada forneceu o conteúdo; abertura direta do PDF encontrou loop de redirecionamento neste ambiente. Não se usa a versão 1.02 antiga como contrato atual. XML próprio do emitente não é garantido pela distribuição; resumo não autoriza criar manifestação para liberar XML.
2. [Documentação atual NFS-e, atualizada em 04/11/2026](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual) e [manual de contribuintes ADN v1.1, 03/11/2026](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-municipios-apis-adn-sistema-nacional-nfs-e-v1-1-20261103.pdf): atores, CNPJ base, alvo por CNPJ/CPF, procuração, `TipoConsulta`, E2244/E2245 e demais rejeições. O nome do arquivo contém “municipios”, mas a capa e o conteúdo são o Manual dos Contribuintes.
3. [Relação oficial de APIs de produção/produção restrita](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao): endpoints distintos dos contribuintes. A leitura pública do Swagger/especificação nos dois ambientes retornou **HTTP 503** neste executor, sem uso de certificado. Os ZIP/XLSX oficiais de XSD/leiaute responderam **HTTP 403**. O JSON de sucesso não foi inferido a partir desses erros: a evidência recuperada posteriormente está identificada abaixo.

## Perfil de sucesso ADN recuperado e limites

Na continuação, a pesquisa na Library localizou `nfse_rebuild_relay_20261104.txt` (1.890.819 bytes, SHA-256 `6e40ee6e0f003f835d97244627370f9f61995ee5953a60222b3d525c57b7cdc1`). Os 70 registros codificados tiveram tamanho/hash conferidos. Somente fontes/documentação selecionadas foram extraídas como referência; nenhum programa externo foi executado, nem o projeto/relay publicado nesta PR. A evidência nova é `docs/swagger-adn.json`, OpenAPI 3.0.1, título “API NFS-e - ADN Contribuinte”, versão v1, 114.164 bytes, SHA-256 `271e957738c53738c97886b1c3c54e34ca129a401ea311b97872fee8d16c99a0`. Trata-se de **snapshot recuperado da referência do usuário**, não de uma especificação obtida ao vivo nesta execução. O Swagger oficial continuou inacessível. Os exemplos XML do Swagger são placeholders, não notas válidas nem prova de homologação.

O perfil `adn-contribuintes-json-v1-recovered-271e9577` usa somente o contrato descrito nesse snapshot: GET `/DFe/{NSU}` exclusivo, `lote=true` explícito (o padrão documentado também é true), NSU `integer/int64`, JSON HTTP 200 com `DOCUMENTOS_LOCALIZADOS`, `TipoConsulta`, `TipoAmbiente` (`PRODUCAO` ou `HOMOLOGACAO` para produção restrita) e `LoteDFe`. Cada pacote possui `NSU`, `ChaveAcesso`, `TipoDocumento`, `TipoEvento`, `ArquivoXml` e `DataHoraGeracao`. Os campos opcionais podem ser nulos, mas NSU e XML completos são obrigatórios para avançar nesta implementação conservadora. Não são presumidos `ultNSU`, `maxNSU`, XML puro sem GZip, outro envelope JSON ou resposta XML do endpoint. Não se fixa o tamanho da chave fiscal a partir do placeholder do Swagger.

- NSUs ADN são comparados numericamente, até 9.223.372.036.854.775.807; ficam como **strings** em recibos/estado para evitar perda de precisão em JavaScript. O limite NF-e continua em 15 dígitos. Exige todos os NSUs maiores que o cursor, sem duplicatas; não exige contiguidade nem ordem do lote. O candidato é o maior NSU devolvido, conforme o contrato exclusivo.
- Todo `ArquivoXml` exige base64/GZip completo, UTF-8 e XML bem formado, sem DTD/entidades. Limites técnicos locais: JSON 20 MiB, XML 20 MiB, soma expandida 80 MiB, até 1.000 pacotes. Esse teto não é uma promessa do tamanho de lote do serviço. Para `NFSE`, exige raiz `NFSe` no namespace nacional e um `infNFSe`; isso **não valida XSD, assinatura, autorização fiscal nem valores**.
- `NFSE`, `DPS`, `EVENTO`, `PEDIDO_REGISTRO_EVENTO` e `CNC` completos são preservados. Eventos recebidos ficam como XMLs sem efeito fiscal; não há execução, transmissão ou alteração de estado fiscal. Tipo novo/NENHUM, XML ausente/inválido, campo incompatível, alerta, erro, ambiente ou modo divergente retêm **o lote inteiro** como pendência com código explicável e JSON original; não há avanço parcial.
- Envelope e cada XML são armazenados por hash na mesma transação de `operations`/`stored_files` que atualiza o cursor. Falha no segundo XML desfaz todos os registros e o avanço. Arquivos materializados são cópias regeneráveis do banco; eventual resíduo de gravação física após rollback não é um recibo canônico e não autoriza avanço. Repetição idempotente não chama a rede. Download individual verifica empresa, exportação, hash e tamanho.
- Avançar cursor significa **captura durável**, não confirmação de importação ou escrituração. `review_pending` continua verdadeiro. A raiz, o tipo e os horários declarados de geração/processamento são metadados do transporte; não se convertem `dhProc`, `dhEmi` ou `dCompet` em data de escrituração. O XML mantém esses campos distintos. A competência solicitada organiza o recibo; não filtra uma distribuição por NSU nem declara a competência fiscal dos documentos retornados.
- O leitor de escrituração NFS-e permanece pendente e a rota de prévia retorna `nfse_bookkeeping_reader_pending`; não cria documentos, títulos ou lançamentos. UI, agendamento e paginação automática também continuam pendentes. O intervalo ADN permanece conservador em uma hora, inclusive em sucesso; não se afirma que esse intervalo seja uma exigência oficial.

O [manual v1.1, conferido também por download direto](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-municipios-apis-adn-sistema-nacional-nfs-e-v1-1-20261103.pdf/@@download/file) confirma alvo exclusivo CNPJ/CPF, mesma base sem procuração, E2244/E2245 e `TipoConsulta`. A [FAQ v1.3 de 06/11/2026, item 28.2](https://www.gov.br/nfse/pt-br/perguntas-frequentes/perguntas-frequentes-nfs-e-v1-3-20261106.pdf/@@download/file) confirma que a autorização específica NFS-e e sua vigência são geridas pelo outorgante na Receita Federal; ela não concede automaticamente poderes pela configuração local do aplicativo. Nenhuma funcionalidade de emissão ou eventos mencionada pela FAQ foi habilitada.

## Consulta mTLS manual e coordenação

As rotas ficam sob a rotina fiscal de importação existente:

| Operação | Rota | Efeito |
|---|---|---|
| Consultar uma página | `POST /api/companies/{cid}/imports/reception/query` | A1, chamada limitada e recibo; sem escrituração automática |
| Consultar resultado | `GET .../imports/reception/receipts/{key}` | Metadados da tentativa/pendência |
| Baixar origem | `GET .../imports/reception/receipts/{key}/download` | Envelope XML ou corpo JSON íntegro, com permissão de exportar |
| Baixar XML ADN | `GET .../imports/reception/receipts/{key}/documents/{nsu}/download` | XML original por NSU do recibo, com isolamento por empresa e permissão de exportar |
| Preparar importação NF-e | `POST .../imports/reception/receipts/{key}/preview` | Mesmo `core.preview_import`, com competência/opções explícitas |

A consulta recebe somente `provider`, `environment`, `period` e `idempotency_key`. O CNPJ vem da empresa ativa; o cursor vem do estado persistido. URLs, certificados, senha, inscrição de outro alvo e NSU arbitrário são recusados no corpo HTTP. Cada chamada busca uma página; não esgota lotes nem agenda futuras consultas. A captura pode consultar uma competência fechada por não alterar a escrituração. A posterior confirmação dos XMLs mantém a exigência de reabertura descrita acima.

`LocalA1Credentials` lê um diretório indicado localmente por `ESCRITURA_RECEPTION_CREDENTIALS_DIR`. A configuração e os PFX não são gravados no banco, enviados pela API, incluídos no Git ou no backup do aplicativo. O diretório exige 0700 e os arquivos 0600, com proprietário corrente e sem symlink final em POSIX. No Windows, a verificação de ACL e a configuração de acesso local permanecem responsabilidade de operação e precisam de homologação própria. Não enviar PFX/senha pelo chat.

Formato de `profiles.json` (valores de inscrição precisam ser substituídos localmente; não é uma configuração pronta):

```json
{
  "companies": {
    "1": {
      "tax_id": "<CNPJ numérico da empresa>",
      "pfx_file": "empresa.pfx",
      "password_env": "ESCRITURA_RECEPTION_PASSWORD_EMPRESA_1",
      "environments": {
        "nfe_distribution": ["homologation"],
        "nfse_adn": ["restricted_production"]
      },
      "allow_adn_procuration": false
    }
  }
}
```

A senha é obtida apenas da variável local nomeada; não existe campo HTTP para ela. A falta de perfil/ambiente interrompe antes da chamada. Produção requer inclusão explícita de `production` no perfil correspondente; não há fallback de ambiente. O transporte deste incremento aceita A1/PFX com **CNPJ numérico**; CPF, A3, certificado em nuvem e CNPJ alfanumérico remoto não foram habilitados. A importação local alfanumérica existente continua preservada.

O CNPJ do certificado é extraído do `otherName` ICP-Brasil OID `2.16.76.1.3.3`, com formato e DV conferidos. Não se confia em CNPJ fornecido pela API nem se usa nome/CN como fallback. Validade temporal é verificada. A chave PKCS#8 temporária permanece criptografada, com permissão restrita, e os arquivos temporários são apagados após carregar o `SSLContext`. Isso não certifica cadeia ICP-Brasil, revogação/LCR, direito de acesso ou autorização fiscal: essas validações dependem do serviço oficial e da homologação externa.

A matriz do ADN segue os dois manuais oficiais: o [v1.0 indicado na solicitação](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-apis-adn-sistema-nacional-nfse.pdf) confirma mesma raiz; o v1.1 acima acrescenta as procurações. Alvo igual ao certificado usa `InscricaoCertificado`, sem parâmetro de outra inscrição. Matriz → filial e filial → matriz da mesma base de oito dígitos usam `cnpjConsulta` completo e modo esperado `CnpjBase`. Outra base é recusada por padrão. A opção local `allow_adn_procuration=true` permite **tentar** a consulta no ADN; não outorga nem prova procuração. O modo esperado é `Procuracao`. `authorization_verified` só é verdadeiro num HTTP 200 do perfil conhecido, com ambiente e `TipoConsulta` correspondentes e todos os pacotes validados; representa a autorização informada nessa resposta, não uma procuração cadastrada pelo aplicativo nem validação independente da vigência futura. Em E2245, inclusive se o retorno trouxer `TipoConsulta=InscricaoCertificado`, o estado é `authorization_pending` e o cursor é preservado.

O transporte usa `http.client.HTTPSConnection`, endpoints oficiais fixos, TLS >= 1.2, hostname e certificado servidor obrigatoriamente verificados, sem proxy automático, redirecionamento ou retry implícito. Só há POST no serviço NF-e de distribuição e GET `/contribuintes/DFe/{NSU}` no ADN. Corpo HTTP limitado a 20 MiB, leitura limitada por timeout/prazo e sem descompressão HTTP implícita. A resposta bruta não aparece em logs/auditoria. Um HTTP 200 da API local pode representar um recibo com rejeição/pendência; consulte sempre `state`, não apenas o status HTTP.

O serviço usa namespaces próprios em `operations`: `fiscal-reception-state-v1` e `fiscal-reception-run-v1`. A chave de estado inclui empresa/CNPJ/provedor/ambiente; matriz e filial não compartilham cursor. Escritas SQLite são serializadas pelas transações existentes; permissões, sessão/contexto, cadastro da empresa e limites operacionais são revalidados antes de reservar e antes de confirmar. Não houve tabela nova, troca de banco ou migração duplicada.

- Lease de dez minutos reservado antes da chamada; outra tentativa concorrente é recusada. A reserva também aplica um intervalo conservador de uma hora para recuperação após interrupção. Um processo que retornar após expirar/perder a reserva não aplica seu resultado.
- Na conclusão válida NF-e, o corpo integral é salvo no `stored_files` existente e o NSU é atualizado na **mesma transação**. Suporte parcial do leitor não descarta pacotes: resumo/evento/leiaute desconhecido continuam no original recebido antes de avançar a captura. Interpretar/importar/escriturar é etapa separada e explícita.
- Sem resposta/erro, 656, retorno inconsistente, ambiente divergente, E2245, JSON ADN desconhecido/incompleto, perda de reserva ou falha de persistência: não há avanço. Falha após gravar o arquivo e antes do commit foi testada por rollback. A mesma chave idempotente não retransmite uma tentativa incerta.
- Resultado persistido pode ser consultado/baixado novamente sem rede. Nova chave durante cooldown é recusada. 137/656/fim do lote NF-e e falhas usam ao menos uma hora; uma página intermediária bem-sucedida permite próxima tentativa após 60 s. HTTP 429/503 respeitam também `Retry-After` numérico com limite de 24 h. Nenhum retry automático foi criado.
- A garantia de lease vale para instâncias que compartilhem esta base SQLite no modelo suportado. Não coordena aplicações externas, outras bases ou hosts com cópias divergentes; não autoriza escalar réplicas SQLite.

Runtime: `cryptography==50.0.0`, `cffi==2.1.1` e `pycparser==3.0` fixados no lock comum com hashes oficiais PyPI; metadados e licenças entram nos pacotes Windows/macOS ARM. No macOS Intel, esses três pins têm marcador de exclusão: a consulta A1 usa o helper Apple nativo descrito adiante. Perfil e permissões são os mesmos; helper ausente/inconsistente retorna erro de instalação, sem downgrade. Importação local continua disponível. As referências MinIO geradas nos três Compose e dois `.env.example` mudam apenas o hash de conteúdo porque a imagem já dependia da base Python. Volumes, mounts e políticas da frente PR35 permanecem fora da alteração; a recepção não usa Redis, MinIO ou PostgreSQL. Nenhuma imagem foi publicada/implantada nesta tarefa.

Fontes técnicas adicionais: [ITI — definição do OID CNPJ](https://www.gov.br/iti/pt-br/central-de-conteudo/resolucao-128-subject-alternative-name-pdf), [PyCA — PKCS#12](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/serialization/#pkcs12), [PyCA — X.509](https://cryptography.io/en/latest/x509/reference/). A referência histórica do OID documenta a identificação do campo, não uma homologação ou declaração de conformidade ICP-Brasil integral.

## Próximos incrementos e dependências

1. Leitor fiscal nacional para prévia/escrituração, parametrização e revisão por empresa/competência, apoiado em XSD/leiautes atuais e fixtures apropriadas. A recepção/download de XMLs e avanço condicionado do NSU ADN estão implementados no perfil recuperado abaixo; a cobertura real por emitente/tomador/intermediário e ambiente depende de homologação externa. Não equivale a recuperar todos os documentos nacionais/municipais.
2. Interface de configuração/consulta, seleção de recibos, fila/agendamento automático e política por empresa de competência/revisão. Reutilizar este serviço e suas permissões, reserva, cooldown e originais; não criar um segundo caminho operacional.
3. Homologação externa autorizada e separada por ambiente/empresa, matriz/filial/procuração, cadeia/LCR e credenciais; validar instalação/ACL e variantes A1 antes de declarar suporte operacional. Certificados reais nunca entram no Git/chat.
4. Ampliação CT-e/MDF-e/NFC-e somente com protocolos, fontes e testes próprios. Não assumir recuperação universal de XMLs emitidos pela distribuição NF-e.
5. PostgreSQL operacional depende da adoção validada da frente própria; manter SQLite nos binários e no núcleo atual, sem migração duplicada ou implantação de Atlas.

## Correção do runtime macOS Intel observada no CI

O [job macOS x64 do CI anterior](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43693260199/job/132751050810), associado ao head `17da177`, falhou ao instalar `cryptography==50.0.0` com `--only-binary`. Os metadados oficiais [PyPI 50.0.0](https://pypi.org/pypi/cryptography/50.0.0/json) mostram wheels macOS somente ARM; o [changelog PyCA](https://cryptography.io/en/latest/changelog/) também registra o encerramento dessa distribuição para Intel. Não foi feito downgrade nem compilação improvisada da biblioteca. A versão antiga [48.0.1 também possui avisos de segurança registrados nos metadados PyPI](https://pypi.org/pypi/cryptography/48.0.1/json); não foi adotada como fallback. Na correção inicial, mTLS ficou temporariamente desabilitado no Intel. Essa restrição foi substituída nesta continuação pelo backend Apple nativo; os marcadores continuam omitindo apenas as dependências PyCA nesse alvo. Windows x64, Linux e macOS ARM conservam os pins existentes. Isso protege a instalação do aplicativo, sem alegar suporte A1 nesse alvo. O novo build nativo continua dependendo do CI.

Foi conferida a inicialização real da API com imports de `cryptography` deliberadamente indisponíveis, em processo sintético Linux; isso prova ausência de dependência no startup, não substitui o teste nativo macOS. O marcador do lock/requirements e os quatro alvos de plataforma estão testados. A mudança no conteúdo do runtime regenerou novamente somente a identidade MinIO nas referências Compose, sem alterar volumes, mounts ou política de atualização. Nenhuma imagem foi publicada ou implantada.

## Validação

Resultados do incremento anterior sobre develop dev.10 (histórico; não comprovam o novo head):

- **332 testes de domínio/API passaram em 127,824 s**, incluindo 38 testes novos de recepção no conjunto da PR (19 do leitor e 19 do transporte/captura). A rodada final usou os pacotes instalados a partir do lock em runtime limpo. A suíte cobre também os três testes de consulta/indicadores da PR38 incorporada.
- **49 testes adicionais de infraestrutura/empacotamento/cache/workflows passaram** em rodada separada. São **381 testes distintos de backend** nesses dois conjuntos, sem somar as repetições. Os 19 testes finais do transporte/captura também passaram separadamente em 5,367 s.
- mTLS real somente em servidor local: GET ADN e POST NF-e com CA/certificados sintéticos, identificação do certificado apresentado e recusa sem certificado cliente. Timeout, tamanho, redirecionamento sem seguimento, ambiente, matriz/filial nos dois sentidos, outra raiz/E2245, reserva, concorrência observada, expiração, revogação de usuário, rollback, repetição e backup/restauração de recibo/cursor conferidos.
- Download das 40 distribuições Linux do runtime com `--require-hashes --only-binary --no-deps`; instalação **offline em venv limpo**, `pip check` sem dependências quebradas, inicialização real da API e leitura XML sintética aprovadas. O lock possui 41 pins incluindo colorama condicional Windows. Não equivale a build nativo ou imagem Docker executada.
- **141 testes frontend passaram** e build Vite concluído em 4,26 s, mantendo o aviso preexistente de chunk acima de 500 kB. Dependências frontend reaproveitadas tinham os mesmos pins; apenas a versão de release mudou ao sincronizar dev.10.
- Checks de sintaxe/diff e resultados de CI devem acompanhar o commit final. `scripts/build.py check` não existe na base; os testes novos entram na descoberta já usada pelo CI. Nenhum workflow foi desabilitado.

Comando do conjunto de domínio/API:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-mtls-runtime-20261115/lib/python3.12/site-packages:tests:. python3 -m unittest test_reception_remote test_reception test_importers test_fiscal_import test_import_revision test_import_reprocessing test_import_payables test_import_masters test_import_package_cleanup test_master_evidence test_operational_settings test_evolution test_core test_xml_billing_parser test_importer_movement_dates test_archives test_archive_pdf_accessories test_business test_management test_bulk_security test_reprocessing_linked_effects test_generated_payables test_journal_query_loading -q
```

Comando de infraestrutura/empacotamento:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-mtls-runtime-20261115/lib/python3.12/site-packages:tests:. python3 -m unittest test_infrastructure test_windows_packaging test_ci_artifacts_cache test_performance_workflows -q
```

Os testes usaram somente fixtures e bancos/certificados temporários sintéticos. Falhas intermediárias de instrumentação/cadeia sintética do teste TLS foram corrigidas; o handshake não foi substituído por um retorno simulado. A alteração do runtime fez o teste de sincronização detectar tags derivadas antigas; elas foram regeneradas, sem retirar o check. A recuperação inicial teve dependências de compactação ausentes e nome de módulo errado no comando; a rodada aprovada foi repetida após corrigir o ambiente. Resultados anteriores não são usados como prova de homologação.

Não executados consulta fiscal externa com certificado real, homologação SEFAZ/ADN, PVA/Prosoft, suíte integral, navegador deste incremento, instaladores nativos ou imagem operacional. CI Windows/macOS/Docker ainda é uma evidência separada e deve ser informado pelo resultado efetivo. Sem dados reais, emissão, cancelamento, manifestação, merge da PR, release ou deploy.

Validação da continuação ADN sobre develop dev.11:

- **424 testes backend passaram na rodada final combinada em 147,011 s**, sobre a árvore com o ajuste de plataforma: domínio/API, 51 testes de recepção, SPED incorporado e 50 de infraestrutura/empacotamento. As rodadas intermediárias de 373 e 101 testes também passaram; não foram somadas à contagem final.
- 141 testes frontend passaram (3,148 s) e build Vite passou (3,71 s), com o aviso preexistente de chunk acima de 500 kB.
- Os 12 novos testes ADN usam exclusivamente JSONs e XMLs sintéticos derivados dos campos do snapshot; não são fixtures fiscais oficiais. Cobrem sucesso, matriz/filial nos dois sentidos, procuração explicitamente permitida, modo divergente, int64 acima da precisão JavaScript, NSU exclusivo, XML ausente/corrompido/DTD/namespace/expansão, lote inteiro retido, download/exportação/integridade, rollback do segundo XML, idempotência e backup/restauração. O teste mTLS local agora transporta o maior NSU int64, com `lote=true`, sem conectar ao ADN.
- Sintaxe, diff e templates derivados conferidos. A correção macOS Intel não equivale a uma instalação nativa aprovada; acompanhar o CI do novo head. Continuam pendentes homologação externa e leitor de escrituração nacional, UI/agendamento e ampliação de documentos/ambientes.

Comando final combinado da continuação (mesmo runtime Linux travado, sem acesso fiscal remoto):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/escritura-mtls-runtime-20261115/lib/python3.12/site-packages:tests:. python3 -m unittest test_reception_adn test_reception_remote test_reception test_importers test_fiscal_import test_import_revision test_import_reprocessing test_import_payables test_import_masters test_import_package_cleanup test_master_evidence test_operational_settings test_evolution test_core test_xml_billing_parser test_importer_movement_dates test_archives test_archive_pdf_accessories test_business test_management test_bulk_security test_reprocessing_linked_effects test_generated_payables test_journal_query_loading test_sped_generator test_sped_native_export test_infrastructure test_windows_packaging test_ci_artifacts_cache test_performance_workflows -q
```

## Investigação complementar: recuperar A1 no macOS Intel

Desabilitar mTLS Intel é uma **lacuna funcional ainda aberta**, não conclusão da recepção completa. Foram examinadas alternativas sem alterar o transporte fiscal em uso:

| Alternativa | Evidência oficial | Avaliação nesta etapa |
|---|---|---|
| PyCA 49/50 compilado no Intel | [Changelog 49](https://cryptography.io/en/50.0.2/changelog/#v49-0-0) remove a plataforma, não apenas o wheel | Compilar não restaura suporte oficial; não adotado |
| PyCA 48.0.1 / pacote de fornecedor | Último wheel universal2 examinado; avisos PyPI; [MacPorts py312-cryptography](https://ports.macports.org/port/py312-cryptography/details/) e seu Portfile consultados ainda fixam 48.0.0 | Não se comprovou uma linha Intel mantida com correções; não houve downgrade. Aviso de biblioteca não prova exploração nesta aplicação |
| Homebrew/OpenSSL/curl | [Homebrew](https://docs.brew.sh/Support-Tiers) classifica Intel como Tier 3 e parou novos bottles. [curl](https://curl.se/libcurl/c/CURLOPT_SSLCERTTYPE.html) condiciona P12 ao backend TLS; [OpenSSL](https://docs.openssl.org/3.5/man1/openssl-pkcs12/) documenta conversão PFX | CLI presente não prova backend, atualização ou distribuição suportada. Exigiria empacotamento verificado, proteção de senha/chave e validação estruturada do CNPJ; não ativado |
| Security.framework + URLSession | [SecPKCS12Import](https://developer.apple.com/documentation/security/secpkcs12import(_:_:_:)) e [URLCredential para identidade](https://developer.apple.com/documentation/foundation/urlcredential/init(identity:certificates:persistence:)) são APIs nativas macOS | Candidato prioritário para evitar exportação da chave e dependência PyCA no Intel; ainda não integrado |
| Servidor Linux/Windows com API existente | Serviço de recepção já revalida empresa, permissões, recibos e cursor | Alternativa arquitetural possível para cliente Intel, mas requer instalação/configuração segura própria e interface; nenhum servidor foi implantado ou certificado transferido |

A Apple documenta a importação de identidade e o uso com URLSession. A [implementação pública Apple de SecPKCS12Import](https://github.com/apple-oss-distributions/Security/blob/main/OSX/libsecurity_keychain/lib/SecImportExport.c) confirma que `kSecImportToMemoryOnly=true` evita a persistência automática no keychain; a importação padrão pode persistir e não deve ser usada inadvertidamente. A [configuração efêmera](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/ephemeral) evita armazenamento persistente da sessão. Isso fundamenta uma prova, não a conformidade fiscal de um adaptador pronto.

Foi acrescentada uma prova **experimental e separada da aplicação**, `scripts/probes/macos_a1.py` + `.swift`, e um workflow exclusivo em runners macOS 15 Intel/ARM. Não muda nem dispensa os gates existentes. Gera PFX moderno sintético AES-256-CBC/MAC SHA-256, passa senha por stdin, importa identidade em memória, compara o certificado DER exato e testa URLSession mTLS num servidor 127.0.0.1 com CA sintética e exigência de certificado cliente. O servidor compara o DER efetivamente recebido. Testa senha errada e ausência de certificado cliente. A âncora sintética é exclusiva dessa prova; não há opção equivalente adicionada ao transporte fiscal. Nenhum endpoint externo ou dado real é usado; arquivos temporários não viram artefato.

A prova não interpreta o OID CNPJ em produção, não substitui o serviço de credenciais, não implementa toda a política de destinos/limites/rejeições e não habilita consultas no Intel. Mesmo um handshake aprovado ainda exige adaptação de CNPJ/validade/cadeia, limites e timeout, redirecionamento/proxy, assinatura/empacotamento do helper, testes de permissões/empresa e homologação externa antes de integrar. A execução Swift não é possível neste executor Linux: o resultado nativo deve vir do workflow, por arquitetura. Até lá, **a solução completa para A1 Intel continua pendente**.

Primeiro resultado nativo: [workflow 43696517442](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43696517442), Intel e ARM, compilou a prova e falhou em `probe_identity_import`, antes do handshake. O gerador observado era `/usr/bin/openssl` **LibreSSL 3.3.6**, não OpenSSL 3. Isso não prova ausência geral de suporte nativo. A próxima variação controlada usa OpenSSL 3 pré-instalado no runner, mantém AES-256/MAC SHA-256, verifica a leitura da própria fixture e distingue status nativo de formato/quantidade de itens. Nenhuma instalação de fornecedor nem downgrade foi executado. A [resposta de engenharia Apple](https://developer.apple.com/forums/thread/779466) relata importação moderna em macOS 15.4, mas isso não substitui a prova desta implementação.

Resultado da segunda prova: [workflow 43696811950](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43696811950) **passou em Intel x86_64/macOS 15.7.9 e ARM64/macOS 15.8.2**. Os geradores observados foram OpenSSL 3.6.3 e 3.5.9 respectivamente. Foram comprovados importação em memória, comparação DER do cliente efetivamente recebido pelo servidor local e rejeição de senha errada/ausência de certificado cliente. Não se fez conversão legacy nem redução dos algoritmos. A variante seguinte acrescenta uma âncora de servidor incorreta como teste negativo. Isso comprova viabilidade dos componentes nativos nessas duas instalações, **não o adaptador fiscal completo nem outras variantes de A1**. O bloqueio restante é integrar e validar o helper com CNPJ/validade e as políticas do serviço; o transporte Intel do aplicativo ainda não foi habilitado.

Também foi examinada a falha do [CI principal 43695689467](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43695689467): a suíte percorreu 927 testes e falhou somente no novo teste de marcadores, por `packaging.requirements` ausente. A pasta local `packaging/` não substitui esse pacote. Foi declarado `packaging==26.3` em `requirements-test.txt` a partir do PyPI oficial, sem alterar runtime ou dispensar o teste; os 24 testes de infraestrutura passaram em venv isolado. Os erros posteriores de navegador nessa execução decorreram de Playwright não instalado após o gate falhar; não constituem validação de navegador. A suíte integral isolada anterior confirmou 927 testes sem falhas (28 skips); a nova regressão dev.12 está registrada adiante. O CI continua sendo evidência separada.

## Integração nativa A1 macOS Intel (continuação em validação)

A base foi sincronizada com develop dev.12 `955404e`, incluindo a PR35 e preservando seus volumes/migração. O conflito era apenas a adição de regras no `.gitignore`; ambas as proteções foram mantidas. Testes de armazenamento e infraestrutura passaram, sem executar migração operacional.

`LocalA1Credentials` passa a selecionar o backend nativo no macOS Intel após validar o mesmo perfil, empresa/ambiente e permissões de arquivo. Windows, Linux e macOS ARM conservam o backend PyCA. O helper `EscrituraA1` usa Security.framework/URLSession, sem biblioteca externa ou exportação da chave privada: CNPJ vem exclusivamente de uma ocorrência do OID `2.16.76.1.3.3` no SAN estruturado, com 14 dígitos e DV válido; não usa CN ou texto localizado. Datas numéricas da API Apple usam referência de 2001 e são convertidas para UTC/Unix. Validade é conferida na inspeção e novamente antes da consulta. Os dois formatos foram observados na prova nativa Intel/ARM, não adivinhados.

O bridge transmite PFX/senha somente por stdin de processo, sem shell, argv, ambiente de credenciais ou logs. Recebe metadados/pin do certificado na inspeção e exige o mesmo certificado/CNPJ na consulta; bytes PFX já lidos permanecem vinculados à identidade em memória. O helper constrói exclusivamente GET ADN por NSU ou SOAP NF-e distNSU a partir de campos validados, com endpoints/ambientes fixos, alvo e mesma raiz/procuração explícita. Não recebe URLs, CA, cabeçalhos arbitrários ou XML de operação do cliente. Consulta limitada por prazo/tamanho, TLS >=1.2, validação padrão Apple de servidor/hostname, redirecionamento recusado, proxy/cache/cookies desabilitados. A prova local usa variante compilada `RECEPTION_TESTING`; o binário de produção recusa seus campos.

Sessão/RBAC/contexto, bloqueios operacionais por empresa, reserva, cooldown, idempotência, originais/cursor atômicos e revisão continuam em `ReceptionService`. Nenhuma permissão ou escrituração é criada pelo helper. O binário é construído nativamente e incluído em `Contents/MacOS/EscrituraA1`, com manifesto em `Contents/Resources/native`. Assinatura, hash, protocolo e arquitetura são conferidos antes do IPC. O hash é calculado após assinatura do código interno; a assinatura externa é refeita sem reescrever o helper, preservando a integridade do manifesto. O smoke do pacote instalado verifica o helper e recusa opções de teste. Instalação antiga/fonte sem helper íntegro recebe erro de instalação, não fallback criptográfico antigo.

A integração está em validação nos runners Intel/ARM, incluindo CNPJ ausente/inválido/duplicado, validade, senha, pin, raiz, campos de teste recusados em produção, mTLS local, CA errada, cliente ausente, redirect, tamanho/codificação e fluxo API→recibo/XML/cursor/permissão. Testes Linux do bridge/serviço não substituem execução Apple nem instalação do pacote. Não houve consulta fiscal externa; permanecem os limites de modelos/ambientes, A1/CPF/A3 e leitor fiscal NFS-e anteriormente descritos.

## Convivência com outros sistemas e futura automação DF-e

Foram confrontadas a [NT 2014.002 v1.30, seção 3.11.4](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=P0U3lU1Fe40%3D) e a [v1.40 de julho/2026, seção 3.11.4](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=uWO2d%2FgTuWg%3D), por conteúdo oficial indexado; as aberturas diretas tiveram timeout/loop de redirecionamento. Aplicações do mesmo ator/CNPJ compartilham a sequência distNSU e devem seguir o último NSU devolvido. Após 137 ou esgotamento informado, é necessário aguardar uma hora; 656 também exige uma hora, e insistir antes do prazo reinicia a espera. Isso descreve o protocolo, não evidencia uma falha nesta instalação ou consultas simultâneas do usuário.

A reserva do Escritura coordena somente instâncias que compartilham esta base. Não coordena outros aplicativos, bases ou fornecedores. Os recibos NF-e incluem aviso `NFE_EXTERNAL_NSU_COORDINATION` com esse alcance; não exigem confirmação adicional nem bloqueiam a consulta por mera presença de outro sistema. A sequência persistida e o cooldown existente continuam sendo aplicados aos fluxos internos. Não foi acrescentado reset arbitrário de NSU nem adoção automática do cursor de uma rejeição.

Para automação futura, manual e agendador devem chamar o mesmo serviço/coordenador; a autoridade da sequência precisa ser única por CNPJ/provedor/ambiente também quando houver mais de um coletor externo. Alternativas práticas são uma coleta central acordada entre sistemas ou importar os XMLs já obtidos pelo coletor existente. Uma integração de handoff deve vincular empresa/ambiente, sequência, recibos/originais duráveis, espera e auditoria antes de atualizar o cursor, com recuperação explícita de lacunas. Essa coordenação externa ainda não existe nesta PR; não se presume que o Escritura possa controlar um fornecedor externo. Os limites da NT NF-e não foram transferidos automaticamente para o ADN NFS-e.

Validação da integração nativa: o [workflow 43700284961](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43700284961) aprovou **Intel e ARM**, incluindo build/assinatura do helper de produção, CNPJ/validade/pin, produção sem campos de teste, mTLS local e API→originais/cursor/permissão. A primeira rodada falhou apenas na geração da fixture vencida (`x509 -days -1` não suportado pelos produtores do CI); foi corrigida com datas absolutas documentadas por `openssl ca`, mantendo a mesma asserção de recusa. A fixture foi conferida por parser independente em Linux. Não houve relaxamento de segurança.

Regressão local dev.12: **967 testes percorridos em 326,984 s, 933 aprovados e 34 skips**, em venv com dependências declaradas. Inclui os novos testes de armazenamento da PR35. A continuação acrescenta um caso nativo de matriz/filial/procuração e a rodada final nativa/empacotamento deve acompanhar o head. O helper de produção não precisa de Xcode nem OpenSSL instalados no computador de destino; essas ferramentas são usadas somente para build e fixtures de CI. Em checkout fonte no Mac, o desenvolvimento exige construir o helper com `python scripts/build_native_a1.py` antes de configurar o A1. Os testes não homologam variantes de PFX reais, cadeia/LCR do cliente ou acesso fiscal remoto.
