# Escritura Integrada

Aplicação única de escrituração fiscal, contábil e financeira para o escritório. Empresa ativa e exercício por módulo acompanham documentos, partidas, títulos, conciliação e relatórios. A competência é escolhida na operação, respeitando os bloqueios mensais.

[Releases estáveis](https://github.com/codisplanfiscalai/escritura-integrada/releases/latest) · [Pré-release contínua](https://github.com/codisplanfiscalai/escritura-integrada/releases/tag/develop) · [Builds](https://github.com/codisplanfiscalai/escritura-integrada/actions) · [Documentação de deploy](docs/DEPLOY.md)

## Instalar no Windows ou macOS

Na [pré-release de desenvolvimento](https://github.com/codisplanfiscalai/escritura-integrada/releases/tag/develop), a linha 0.7 preserva os instaladores introduzidos na 0.6:

- Windows x64: `EscrituraIntegrada-<versão>-windows-x64-setup.exe`, com atualização da mesma instalação, backup e migração da distribuição portátil. O ZIP continua disponível.
- macOS 15 ou posterior: `EscrituraIntegrada-<versão>-macos-arm64.pkg` para Apple Silicon e `...-macos-x64.pkg` para Intel, construídos e testados separadamente.

O aplicativo inclui Python, Qt/WebEngine, frontend e dependências; o uso normal dispensa terminal ou serviço Windows. Programa e dados ficam separados. A desinstalação preserva os dados. Encerre pelo menu **Sair** no tray/barra de menus antes de atualizar. **Abrir, Iniciar, Parar, Reiniciar, Configurações** e iniciar minimizado permanecem disponíveis.

Consulte [instalação, atualização e recuperação](docs/DISTRIBUICAO_DESKTOP.md). Os pacotes ainda não possuem Authenticode/Developer ID/notarização; os testes nativos não certificam Gatekeeper/SmartScreen. A release estável 0.4.1 conserva sua distribuição anterior.

## Executar com Docker

Use o pacote de deploy da release correspondente. Os ambientes ficam em diretórios separados:

- `deploy/production/`: produção, com imagem de release estável.
- `deploy/develop/`: homologação, com imagem da pré-release.

O pacote gerado contém `compose.yaml` e `.env`; no repositório, `.env.example` documenta as opções. Os serviços são consumidos como **imagens GHCR**, sem build, montagem de código-fonte ou instalação de dependências na máquina de destino.

No diretório do ambiente:

```bash
docker compose pull
docker compose up -d
docker compose ps
```

**Apenas a porta da aplicação é publicada.** O endereço e a porta são configuráveis; o padrão de acesso é local. Os ambientes usam projetos e volumes separados. A interface, API e arquivos estáticos são atendidos na mesma origem.

O backend atual utiliza SQLite em volume local persistente. As imagens de Redis, PostgreSQL, MySQL e MinIO são disponibilizadas em perfis opcionais de infraestrutura, conectadas somente à rede interna. Ativar um perfil não altera o backend da aplicação nem transforma esses serviços em integrações já implementadas. Não são abertas portas de banco, Redis ou console MinIO.

O pacote de imagens `EscrituraIntegrada-<versão>-linux-amd64-images.tar.gz` permite carregar aplicação, base e recursos da infraestrutura sem baixar as imagens no servidor de destino:

```bash
docker load -i EscrituraIntegrada-<versão>-linux-amd64-images.tar.gz
docker compose up -d --pull never
```

A visibilidade de um pacote GHCR é independente da visibilidade do repositório. Se a imagem estiver privada, o pull exige autenticação com permissão de leitura. O pacote offline usa as imagens já carregadas. As regras de segredos, perfis, volumes, atualização e verificação estão em [DEPLOY.md](docs/DEPLOY.md).

## Branches, versões e publicação

| Linha | Resultado |
|---|---|
| `main` | Versão SemVer estável, tag `vX.Y.Z` e release preservada |
| `develop` | Versão `X.Y.Z-dev.N` superior à versão da `main`; uma única pré-release/tag móvel `develop` |
| Pull request | Testes e validação de build; sem publicação |

Exemplo: com `main` em `0.4.0`, desenvolvimento publica `0.4.1-dev.N`. Ao promover `0.4.1` para a linha estável, desenvolvimento avança para pelo menos `0.4.2-dev.N`.

O pipeline calcula a versão, sincroniza os manifests, testa o núcleo e a interface, constrói os pacotes Windows/macOS e as imagens, executa os respectivos smokes e publica assets com manifestos e SHA-256. A pré-release atualiza o mesmo marcador; releases estáveis não são reescritas. Uma publicação estável sincroniza a versão de desenvolvimento e solicita explicitamente seu novo workflow.

Workflows:

- `ci.yml`: validação de pull requests.
- `release.yml`: construção e publicação de `main`/`develop`, também com execução manual.
- `cache-cleanup.yml`: manutenção agendada ou manual dos caches do Actions, sem excluir releases estáveis.

Versionamento, concorrência, recuperação de falhas, caches e comandos de manutenção estão em [CI_CD.md](docs/CI_CD.md). O resultado de uma distribuição é comprovado pelo run e pelos assets publicados, não apenas pela presença de um workflow neste repositório.

## Recursos do aplicativo

Na linha 0.8 em desenvolvimento, Fiscal → **CFOP e associações** oferece a referência completa do Anexo II consultado no CONFAZ, com 619 códigos e notas. A importação pode escriturar os documentos diretamente, com associações revisadas por empresa; a escrituração permite correções posteriores rastreáveis enquanto os períodos e efeitos vinculados permitirem. O fluxo de conferência individual continua disponível. Consulte [cobertura, origem, operação e limites](docs/ESCRITURACAO_FISCAL_0_8.md).

| Área | Disponível |
|---|---|
| Empresas e cadastros | Empresas, estabelecimentos, participantes, produtos, serviços e históricos; consultas CNPJ/CEP revisáveis, múltiplas IEs e versões |
| Documentos fiscais | Entradas/saídas, itens vinculados aos cadastros, revisão, escrituração com geração transacional de parcelas e contabilização por modelo, consulta da origem e reversão |
| Importações | Fiscal e extratos existentes; CSV contábil (partidas, saldos, contas) e financeiro (títulos) com menus/permissões próprios, seleção explícita e diagnóstico mensal |
| Auditor Fiscal | Python integrado: auditoria interna/avulsa, snapshots, XML/eventos, recálculos delimitados, catálogos XLSX/JSON revisados, achados/tratamento, reprocessamento e PDF/Excel; DANFE 55 em Python |
| Digitação contínua | Salvar e novo, padrões opcionais, Alt+N/Alt+S, Ctrl+Enter para partida, Tab/Shift+Tab e Esc; preservação de erro e idempotência |
| Arquivos e backup | Originais por empresa/ano/hash, backup consistente integral, restauração assistida em pasta nova e verificação de registros, valores e vínculos |
| Contabilidade | Plano por empresa, centros de custo, saldos iniciais, múltiplas partidas balanceadas, modelos com vigência e estornos rastreáveis |
| Financeiro | Pagar/receber, parcelas, baixas parciais/totais com juros, multa e desconto; estorno de baixa e renegociação reversível |
| Conciliação | Vínculos individuais ou rateados; baixa somente mediante escolha explícita; consulta de títulos e pagamentos por participante |
| Exercícios e acessos | Doze meses por exercício/empresa/módulo; bloqueios independentes; grupos, concessões/bloqueios individuais, auditoria e permissões efetivas |
| Relatórios | Diário, Diário Consolidado por dia, Razão, Balancete, centros de custo, Balanço/DRE por classificação, fiscal, títulos, caixa e participantes; CSV e impressão/PDF |
| Parâmetros | CFOP, NCM, receitas, serviços, regras com vigência/versões e modelos reutilizáveis |
| Pré-apuração | Bases revisadas, regras versionadas por tributo, ajustes, memória de cálculo e identificação de alterações posteriores |
| Prosoft | Prévia e exportação CTBLCTOS LC1/LC2, com mapeamentos, validação de posições/tamanhos e confirmação |
| Competências | Fechamento fiscal e contábil independentes, com reabertura motivada |
| Acesso | Administrador, operador e consulta, com permissões por empresa |

As guias compartilham a empresa e preservam o exercício de cada módulo. O mês ou intervalo é definido na operação. Editar outra empresa não a ativa. Modais preservam seu destino, e o servidor confere novamente contexto, propriedade dos registros e bloqueios dentro da transação.

## Limites que permanecem explícitos

- Regras e catálogos fiscais começam vazios. A simulação matemática não constitui apuração legal automática nem aprovação tributária.
- SPED corresponde ao perfil parcial documentado de EFD ICMS/IPI; não abrange todas as obrigações. Compactados são limitados por tamanho, quantidade, profundidade e codecs; arquivos criptografados ou multipartes são rejeitados. RAR comprimido depende de libarchive/bsdtar no Docker ou tar compatível do Windows. Transmissão de obrigações não está implementada.
- XML, bancos e leiautes reais exigem homologação. O código recuperado das referências não foi tratado como fonte original completa ou regra fiscal comprovada.
- O Razão possui modelo baseado no PDF fornecido, com comparação numérica e visual parcial. Os demais modelos mantêm saídas internas; ECD/ECF, livros legais, encerramento anual e consolidação entre empresas não estão implementados. Balanço/DRE exigem classificação explícita do plano; não presumem o encerramento do resultado.
- CTBLCTOS segue o PDF fornecido, limitado a LC1/LC2. Importação efetiva na Prosoft, versões da instalação de destino, leiaute fiscal e registros CTA/TRC/SLD permanecem sujeitos a implementação/homologação. Não há escrita na base Prosoft.
- Perfis são por empresa, sem permissões por campo. A restauração por empresa/exercício isolado e os adaptadores PostgreSQL/MySQL/Redis/MinIO continuam pendentes. O backup e a restauração implementados abrangem o banco integral e seus originais.
- Consultas dependem da cobertura e disponibilidade dos provedores. Ausência de IE não significa isenção. CNPJ alfanumérico é cadastrado manualmente; consulta externa numérica não certifica regime tributário.
- O banco SQLite deve permanecer em disco local, com uma instância gravadora por instalação. Bases Windows e Docker diferentes não se sincronizam automaticamente.

Detalhamento de origem, cobertura, decisões de persistência e pendências da etapa: [EVOLUCAO_0_7.md](docs/EVOLUCAO_0_7.md).

## Desenvolvimento e testes

Requisitos de construção: Python 3.12, Node.js 24 e npm. Qt é necessário somente para o desktop. As versões da interface e da API são derivadas dos manifests sincronizados pelo versionamento.

```bash
python -m pip install -r requirements-test.txt
npm --prefix frontend ci
npm --prefix frontend run build
python -m unittest discover -s tests -v
node --test frontend/tests/date-input.test.js
```

Para desenvolvimento pelo navegador, depois de compilar a interface:

```bash
python -m uvicorn app.api:app --host 127.0.0.1 --port 8765
```

`ESCRITURA_DATA_DIR` seleciona a pasta de dados. O modo normal começa vazio. `ESCRITURA_DEMO=1` habilita deliberadamente dados fictícios e deve usar outra pasta; não converta uma base demonstrativa em base operacional.

## Organização

| Caminho | Conteúdo |
|---|---|
| `app/` | API, domínio, banco, importadores e aplicativo gráfico |
| `frontend/` | Interface Vue, componentes, modais, estilos e testes de datas |
| `tests/` | Testes e fixtures sintéticas |
| `docker/` | Bases, imagens de infraestrutura e catálogo de fontes |
| `deploy/` | Compose e opções de ambiente para produção/desenvolvimento |
| `scripts/` | Construção, validação, empacotamento e automação de publicação |
| `.github/workflows/` | CI, release e manutenção de caches |
| `docs/` | Contratos, arquitetura, distribuição e validação |

[Operação 0.5](docs/OPERACAO_0_5.md) · [Diagnóstico e histórico](docs/DIAGNOSTICO_EXPANSAO_0_5.md) · [Matriz de rastreabilidade](docs/MATRIZ_RASTREABILIDADE.md) · [Validação 0.5](docs/VALIDACAO_0_5.md) · [Contrato da API](docs/API.md)

A [expansão 0.6](docs/EXPANSAO_0_6.md) documenta a precedência de permissões, a apuração revisada, a matriz de implementação/validação e as limitações concretas.

Os cenários e os limites dos testes estão em [VALIDACAO_0_6.md](docs/VALIDACAO_0_6.md).
