# Recepção DF-e / NFS-e: consulta mTLS e importação revisada

Base inicial dev.9 `3a6ab4c`; atualização sincronizada com develop dev.10 `6344584593f3a64126ef69095b7645760b716095`, preservando a PR38. Desenvolvimento em worktree exclusiva `escritura-reception-20261115`. A PR41 continua draft, sem integração em develop/main, release, deploy ou mudança de banco operacional. A recepção manual de arquivo e o transporte mTLS fazem parte da mesma PR; nenhuma consulta fiscal externa foi executada nesta validação.

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

Para ADN, `adn_rejection` normaliza códigos documentados, sem persistir descrições potencialmente privadas. E2245 resulta em autorização pendente, mantém exatamente o cursor fornecido e nunca deduz procuração a partir de `TipoConsulta` de uma rejeição. O serviço de captura usa essa rotina após o transporte. O JSON de sucesso ADN é preservado como origem opaca até confirmação do contrato, sem inferir XMLs ou avanço de NSU. Não há UI nova de configuração/consulta.

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
| NFS-e Nacional emitida/tomada/intermediada | Sem leitor de XML nacional integrado nesta PR | GET mTLS e guarda/download do corpo íntegro; parser de sucesso e leitor XML nacional pendentes, cursor não avança | Produção e produção restrita separados; CNPJ titular/matriz/filial/procuração testados com fixtures. Sem homologação externa |
| NFS-e municipal/outros documentos | Sem ampliação nesta PR | Não implementada | Não presumir que todos os municípios/documentos estão disponíveis no ADN |

## Fontes oficiais e limites da verificação

Consultadas em 15/11/2026:

1. [NT NF-e 2014.002 v1.40, julho/2026](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=uWO2d%2FgTuWg%3D): distribuição, atores, resumos, `distNSU`, janela e consumo indevido. A consulta pública indexada forneceu o conteúdo; abertura direta do PDF encontrou loop de redirecionamento neste ambiente. Não se usa a versão 1.02 antiga como contrato atual. XML próprio do emitente não é garantido pela distribuição; resumo não autoriza criar manifestação para liberar XML.
2. [Documentação atual NFS-e, atualizada em 04/11/2026](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual) e [manual de contribuintes ADN v1.1, 03/11/2026](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-municipios-apis-adn-sistema-nacional-nfs-e-v1-1-20261103.pdf): atores, CNPJ base, alvo por CNPJ/CPF, procuração, `TipoConsulta`, E2244/E2245 e demais rejeições. O nome do arquivo contém “municipios”, mas a capa e o conteúdo são o Manual dos Contribuintes.
3. [Relação oficial de APIs de produção/produção restrita](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao): endpoints distintos dos contribuintes. A leitura pública do Swagger/especificação nos dois ambientes retornou **HTTP 503** neste executor, sem uso de certificado. Os ZIP/XLSX oficiais de XSD/leiaute responderam **HTTP 403**. Não foi inferido um JSON de sucesso.

## Consulta mTLS manual e coordenação

As rotas ficam sob a rotina fiscal de importação existente:

| Operação | Rota | Efeito |
|---|---|---|
| Consultar uma página | `POST /api/companies/{cid}/imports/reception/query` | A1, chamada limitada e recibo; sem escrituração automática |
| Consultar resultado | `GET .../imports/reception/receipts/{key}` | Metadados da tentativa/pendência |
| Baixar origem | `GET .../imports/reception/receipts/{key}/download` | Envelope XML ou corpo JSON íntegro, com permissão de exportar |
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

A matriz do ADN segue os dois manuais oficiais: o [v1.0 indicado na solicitação](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-apis-adn-sistema-nacional-nfse.pdf) confirma mesma raiz; o v1.1 acima acrescenta as procurações. Alvo igual ao certificado usa `InscricaoCertificado`, sem parâmetro de outra inscrição. Matriz → filial e filial → matriz da mesma base de oito dígitos usam `cnpjConsulta` completo e modo esperado `CnpjBase`. Outra base é recusada por padrão. A opção local `allow_adn_procuration=true` permite **tentar** a consulta no ADN; não outorga nem prova procuração. O modo esperado é `Procuracao`, mas `authorization_verified` continua falso enquanto não houver contrato/retorno validado. Em E2245, inclusive se o retorno trouxer `TipoConsulta=InscricaoCertificado`, o estado é `authorization_pending` e o cursor é preservado.

O transporte usa `http.client.HTTPSConnection`, endpoints oficiais fixos, TLS >= 1.2, hostname e certificado servidor obrigatoriamente verificados, sem proxy automático, redirecionamento ou retry implícito. Só há POST no serviço NF-e de distribuição e GET `/contribuintes/DFe/{NSU}` no ADN. Corpo HTTP limitado a 20 MiB, leitura limitada por timeout/prazo e sem descompressão HTTP implícita. A resposta bruta não aparece em logs/auditoria. Um HTTP 200 da API local pode representar um recibo com rejeição/pendência; consulte sempre `state`, não apenas o status HTTP.

O serviço usa namespaces próprios em `operations`: `fiscal-reception-state-v1` e `fiscal-reception-run-v1`. A chave de estado inclui empresa/CNPJ/provedor/ambiente; matriz e filial não compartilham cursor. Escritas SQLite são serializadas pelas transações existentes; permissões, sessão/contexto, cadastro da empresa e limites operacionais são revalidados antes de reservar e antes de confirmar. Não houve tabela nova, troca de banco ou migração duplicada.

- Lease de dez minutos reservado antes da chamada; outra tentativa concorrente é recusada. A reserva também aplica um intervalo conservador de uma hora para recuperação após interrupção. Um processo que retornar após expirar/perder a reserva não aplica seu resultado.
- Na conclusão válida NF-e, o corpo integral é salvo no `stored_files` existente e o NSU é atualizado na **mesma transação**. Suporte parcial do leitor não descarta pacotes: resumo/evento/leiaute desconhecido continuam no original recebido antes de avançar a captura. Interpretar/importar/escriturar é etapa separada e explícita.
- Sem resposta/erro, 656, retorno inconsistente, ambiente divergente, E2245, JSON ADN não confirmado, perda de reserva ou falha de persistência: não há avanço. Falha após gravar o arquivo e antes do commit foi testada por rollback. A mesma chave idempotente não retransmite uma tentativa incerta.
- Resultado persistido pode ser consultado/baixado novamente sem rede. Nova chave durante cooldown é recusada. 137/656/fim do lote NF-e e falhas usam ao menos uma hora; uma página intermediária bem-sucedida permite próxima tentativa após 60 s. HTTP 429/503 respeitam também `Retry-After` numérico com limite de 24 h. Nenhum retry automático foi criado.
- A garantia de lease vale para instâncias que compartilhem esta base SQLite no modelo suportado. Não coordena aplicações externas, outras bases ou hosts com cópias divergentes; não autoriza escalar réplicas SQLite.

Runtime: `cryptography==50.0.0`, `cffi==2.1.1` e `pycparser==3.0` fixados no lock comum com hashes oficiais PyPI; metadados e licenças entram nos pacotes Windows/macOS. As referências MinIO geradas nos três Compose e dois `.env.example` mudam apenas o hash de conteúdo porque a imagem já dependia da base Python. Volumes, mounts e políticas da frente PR35 permanecem fora da alteração; a recepção não usa Redis, MinIO ou PostgreSQL. Nenhuma imagem foi publicada/implantada nesta tarefa.

Fontes técnicas adicionais: [ITI — definição do OID CNPJ](https://www.gov.br/iti/pt-br/central-de-conteudo/resolucao-128-subject-alternative-name-pdf), [PyCA — PKCS#12](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/serialization/#pkcs12), [PyCA — X.509](https://cryptography.io/en/latest/x509/reference/). A referência histórica do OID documenta a identificação do campo, não uma homologação ou declaração de conformidade ICP-Brasil integral.

## Próximos incrementos e dependências

1. Contrato oficial de sucesso ADN/fixtures oficiais e leitor nacional XML, obtenção de todos os documentos de emitente/tomador/intermediário, preservação e download individual. O corpo já é recebido e guardado; XMLs e avanço de NSU ADN continuam pendentes.
2. Interface de configuração/consulta, seleção de recibos, fila/agendamento automático e política por empresa de competência/revisão. Reutilizar este serviço e suas permissões, reserva, cooldown e originais; não criar um segundo caminho operacional.
3. Homologação externa autorizada e separada por ambiente/empresa, matriz/filial/procuração, cadeia/LCR e credenciais; validar instalação/ACL e variantes A1 antes de declarar suporte operacional. Certificados reais nunca entram no Git/chat.
4. Ampliação CT-e/MDF-e/NFC-e somente com protocolos, fontes e testes próprios. Não assumir recuperação universal de XMLs emitidos pela distribuição NF-e.
5. PostgreSQL operacional depende da adoção validada da frente própria; manter SQLite nos binários e no núcleo atual, sem migração duplicada ou implantação de Atlas.

## Validação

Resultados desta continuação sobre develop dev.10:

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
