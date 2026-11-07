# Diagnóstico e execução da expansão 0.5

Data da análise: 07/11/2026. Base confrontada: `develop` em `8a1cfb2156ab8fb3660f6d0d53811b4c6aa41916` (0.4.2-dev.5), `main` em `438ffd6f40f54e4255f35f19a8e495095683b7e9` (0.4.1). O desenvolvimento desta etapa não promove uma versão estável.

## Histórico efetivamente recuperado

O arquivo **Projetos de engenharia reversa.mhtml** foi lido como MIME, com decodificação integral do HTML e extração do texto da conversa. SHA-256 do anexo: `8bc5503e5973aac8f8ed1b139b0eeaf4fa3376b5c03ec1e3686ccf9fa5561d51`.

A sequência visível contém três solicitações principais e suas entregas:

1. Recuperação dos 18 executáveis: projetos Ghidra, pseudocódigo, Assembly, metadados, formulários e inventário. A entrega informa 18.994 funções emitidas e 1.648 falhas, sem equivalência em execução ou projetos VB6 recompiláveis.
2. Criação de aplicação independente: núcleo Python/FastAPI, Vue, empresas por sessão, documentos, partidas, títulos, conciliação individual, regras versionadas e bloqueios independentes. A primeira entrega registrava 58 testes e deixava pendências em importação pela interface, Windows, Docker, apuração legal e integração de destino.
3. Publicação no repositório indicado: `main`/`develop`, SemVer, uma pré-release contínua, pacote Windows, imagens GHCR, dependências, pacotes Compose e offline. O histórico termina em 0.4.1 estável / 0.4.2-dev.5, com 104 testes Python e cinco testes de datas. O código remoto confirma a evolução; portanto, pendências antigas de infraestrutura não foram tratadas como ausência de código.

Há links de navegação para outras conversas/ramificações. Seus corpos não estão incorporados ao MHTML. Nenhuma decisão invisível foi presumida. A pendência de uma tentativa posterior de reexecução de workflow não foi interpretada como falha da publicação já concluída.

## Materiais localizados e limites

| Material | Leitura/verificação nesta etapa | Limite |
|---|---|---|
| MHTML anexado | Conteúdo textual integral, decisões e links | Não contém o corpo de todas as conversas externas mencionadas |
| Projetos_Engenharia_Reversa.zip | Pacote disponível; 18 originais conferidos por SHA-256; inventário de todos os 281 `.frm`/`.ctl` | Não foram executados os programas nem auditados linha a linha os 2,82 GB de resultados |
| Inventario_Projetos.csv | 18 finalidades, versões, controles, funções e falhas confrontados | Contagem de pseudocódigo não mede cobertura funcional |
| Metadados e formulários | Varredura sistemática de nomes, controles e rótulos dos 18 projetos | ActiveX, recursos binários e chamadas externas não expõem toda a regra |
| 40 prints de referência | Arquivos localizados; telas de empresas, documentos, Diário e conciliações inspecionadas | Não foi afirmada inspeção visual integral dos 40 prints nesta etapa |
| DIX_092026_Pacote_Integracao_Prosoft.zip | Layout CTBLCTOS integral e especificações de integração disponíveis | Dados reais do pacote não foram incluídos no repositório nem em testes |
| LAYOUT_CTBLCTOS.PDF | LC1 de 448 / LC2 de 342 posições; simples e detalhado | Homologação no sistema de destino ainda necessária; CTA/TRC/SLD não exportados nesta etapa |
| Layouts fiscais e modelos XLSX do pacote | Identificados no pacote | Exportação fiscal Prosoft por esses perfis não está implementada |

Materiais não disponíveis para validação integral: projetos-fonte VB6 originais recompiláveis; conjunto completo das DLLs/OCXs externos e respectivas implementações; ambiente legado funcional com bases de teste e licenças; acesso à instalação Prosoft de destino; casos fiscais homologados por regime/UF/município e vigência; contratos/credenciais comerciais dos provedores cadastrais. A referência a `PROEMPCTB.DLL`, `PROEMPLFS.DLL`, `PROEMPGER.DLL` ou `Wkb.Contabil.Plugins.Conciliacao` não recupera seus corpos.

## Diagnóstico do código e implementação

O ponto de partida já possuía isolamento de empresa por sessão, transações SQLite, partidas equilibradas, importação em duas fases, arquivos originais, deduplicação documental, bloqueios e distribuição. A expansão conserva esses contratos e acrescenta serviços em módulos próprios; `BusinessCore` compõe o núcleo anterior. A migração é aditiva e transacional, inclusive para baixas antigas.

| Etapa | Expansão funcional | Evidência de validação |
|---|---|---|
| Cadastros | Participantes com papéis, estabelecimentos, produtos, serviços, históricos, modelos contábeis; múltiplas IEs e perfil cadastral; comparação antes de aplicar consultas | Testes de identidade, versões, empresa, cache, fallback e normalização; aceitação de interface em `scripts/smoke_browser.py` |
| Fiscal → contábil → financeiro | Seleção de cadastros, modelo revisado ou partidas explícitas, parcelas da origem ou informadas, gravação atômica, reversão e trilha | Testes de integração, soma das parcelas, competência fechada, repetição e reversão |
| Financeiro | Principal, juros, multa, desconto, caixa efetivo, baixa parcial/total, estorno, renegociação e reversão do acordo | Testes de saldos, concorrência, partidas, caixa e efeitos dependentes |
| Conciliação | Sugestões, vínculo individual preservado, múltiplos títulos por movimento, um título em diferentes movimentos, baixa opcional explícita e desfazimento de vínculos | Testes de excesso, rollback e preservação da baixa ao desfazer vínculo |
| Contábil e relatórios | Classificação explícita das contas, saldos iniciais balanceados, Diário, Diário Consolidado da empresa, Razão, Balancete, centro de custo, Balanço e DRE internos; livros auxiliares fiscal/financeiro/caixa | Totais em centavos, saldos anteriores, estornos, agrupamentos, mapeamento obrigatório e origem |
| Pré-apuração | Memórias por tributo, regras revisadas/vigentes, bases e efeitos escolhidos, ajustes, arredondamento e identificação de origem alterada | Testes matemáticos, segregação IBS/CBS, validade, bloqueio fiscal e obsolescência da memória |
| Prosoft | Prévia LC1/LC2, mapeamentos confirmados, terceiros/centros, recusa de truncamento, revisão ASCII, lote imutável e download | Posições e comprimentos de registros, débitos/créditos, mapeamento e prévia obsoleta |
| Acesso | Administrador, operador e consulta; atribuição de empresas; revogação de sessões e nova checagem sob lock de escrita | Testes de leitura indevida, escrita vedada e revogação |
| Distribuição | Núcleo único e tray preservados; leitores novos no lock comum; teste Chromium acrescido aos gates | Suite local e resultados dos jobs vinculados à revisão publicada |

## Limites funcionais que continuam explícitos

- A pré-apuração **não** determina automaticamente incidência, crédito admissível, CST/cClassTrib, benefício, regime ou alíquota legal. A taxa e a base são escolhas revisadas do escritório. Não há declaração transmitida, homologação PVA ou apuração completa de todos os regimes. Regras antigas dos executáveis não foram ativadas como regras atuais.
- Há relatórios internos utilizáveis para conferência, mas não todos os demonstrativos legais do legado: DFC/DLPA/DMPL, termos de abertura/encerramento, consolidação entre pessoas jurídicas e layouts oficiais setoriais permanecem pendentes.
- O plano referencial, estrutura sintética arbitrária, encerramento automático do resultado e contas com terceiros variáveis por partida demandam perfis adicionais. CTBLCTOS nesta etapa exporta lançamentos com contas/terceiros existentes no destino; não cadastra CTA/TRC/SLD.
- A conciliação de participantes compara títulos/origem/baixas. Não reproduz integralmente a conciliação contábil histórica por conta/terceiro com eliminação, agrupamentos arbitrários e algoritmos de todos os bancos.
- NFS-e manual está disponível; XML NFS-e nacional/municipal ainda exige perfis próprios. SPED é o subconjunto documentado; não é um gerador universal de obrigações.
- PostgreSQL, MySQL, Redis e MinIO continuam **imagens opcionais**, sem adaptadores de persistência, fila ou armazenamento utilizados pelo núcleo. A aplicação usa SQLite local. Publicação de imagens não é integração funcional.
- Windows x64 é o alvo estabelecido. x86 e ARM64 não foram acrescentados. Não há sincronização automática entre bancos independentes de Windows e Docker.

Consulte a [matriz de rastreabilidade](MATRIZ_RASTREABILIDADE.md), os [contratos e limites de operação](OPERACAO_0_5.md) e o [registro de validação](VALIDACAO_0_5.md).

A cópia `Projetos de engenharia reversa(1).mhtml` também foi conferida: possui os mesmos 4.151.433 bytes e SHA-256 `8bc5503e5973aac8f8ed1b139b0eeaf4fa3376b5c03ec1e3686ccf9fa5561d51` do MHTML lido, sem conteúdo adicional de ramificações.
