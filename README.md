# Escritura Integrada

Aplicação única de escrituração fiscal, contábil e financeira para o escritório. Empresa ativa e competência acompanham documentos, partidas, títulos, conciliação e relatórios.

[Releases estáveis](https://github.com/codisplanfiscalai/escritura-integrada/releases/latest) · [Pré-release contínua](https://github.com/codisplanfiscalai/escritura-integrada/releases/tag/develop) · [Builds](https://github.com/codisplanfiscalai/escritura-integrada/actions) · [Documentação de deploy](docs/DEPLOY.md)

## Executar no Windows

1. Abra a release estável ou a pré-release de desenvolvimento.
2. Baixe o arquivo `EscrituraIntegrada-<versão>-windows-x64.zip`.
3. Extraia o diretório completo e abra **EscrituraIntegrada.exe**.
4. Na primeira execução, crie o acesso administrativo pela interface.

O pacote contém Python, Qt/WebEngine, interface compilada, ícone e dependências. Não exige Python ou Node instalados, conexão com a internet para o núcleo local, nem instalação de serviço Windows. Os arquivos auxiliares devem permanecer junto ao executável.

O ícone da área de notificação oferece abertura da aplicação e administração de iniciar, parar, reiniciar, consultar status e configurar a execução. A preferência **Iniciar minimizado** vale para a abertura seguinte. Dados e configurações ficam fora do diretório do programa. Use **Sair** no tray para encerrar a execução local.

Os binários são construídos no runner Windows e passam por um smoke do executável empacotado. Isso comprova inicialização, saúde, renderização básica e encerramento; não substitui a avaliação dos fluxos do escritório ou de todas as versões do Windows. Consulte [distribuição Windows](docs/DISTRIBUICAO_WINDOWS.md).

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

O pipeline calcula a versão, sincroniza os manifests, testa o núcleo e a interface, constrói o pacote Windows e as imagens, executa os respectivos smokes e publica assets com manifestos e SHA-256. A pré-release atualiza o mesmo marcador; releases estáveis não são reescritas. Uma publicação estável sincroniza a versão de desenvolvimento e solicita explicitamente seu novo workflow.

Workflows:

- `ci.yml`: validação de pull requests.
- `release.yml`: construção e publicação de `main`/`develop`, também com execução manual.
- `cache-cleanup.yml`: manutenção agendada ou manual dos caches do Actions, sem excluir releases estáveis.

Versionamento, concorrência, recuperação de falhas, caches e comandos de manutenção estão em [CI_CD.md](docs/CI_CD.md). O resultado de uma distribuição é comprovado pelo run e pelos assets publicados, não apenas pela presença de um workflow neste repositório.

## Recursos do aplicativo

| Área | Disponível |
|---|---|
| Empresas | Cadastro, edição em modal, ativação explícita, CNPJ numérico/alfanumérico e controle de versão |
| Documentos fiscais | Entradas/saídas, itens, origem, revisão e escrituração com contabilização opcional |
| Importações | XML, SPED parcial, ZIP e formatos bancários, com prévia, diagnósticos, origem e confirmação |
| Contabilidade | Plano por empresa, centros de custo, partidas balanceadas e estorno rastreável |
| Financeiro | Pagar/receber, baixa parcial, proteção de saldo e contabilização escolhida |
| Conciliação | Correspondência individual entre movimento bancário e título, com justificativa |
| Relatórios | Diário, Razão por conta e Balancete, filtros por centro, CSV e impressão/PDF |
| Parâmetros | CFOP, NCM, receitas, serviços, regras com vigência/versões e modelos reutilizáveis |
| Competências | Fechamento fiscal e contábil independentes, com reabertura motivada |

As guias compartilham a empresa e a competência do cabeçalho. Editar outra empresa não a ativa. Modais preservam seu destino, e o servidor confere novamente contexto, propriedade dos registros e bloqueios dentro da transação.

## Limites que permanecem explícitos

- Regras e catálogos fiscais começam vazios. A simulação matemática não constitui apuração legal automática nem aprovação tributária.
- SPED corresponde ao perfil parcial documentado de EFD ICMS/IPI; não abrange todas as obrigações. RAR/7z e transmissão de obrigações não estão implementados.
- XML, bancos e leiautes reais exigem homologação. O código recuperado das referências não foi tratado como fonte original completa ou regra fiscal comprovada.
- Relatórios são internos; ECD/ECF, livros legais, encerramento anual e consolidação não estão implementados.
- O código de correspondência Prosoft é cadastral. Não há escrita na base Prosoft nem exportação/sincronização homologada.
- O acesso atual é administrativo. Perfis detalhados por operador/empresa, backup online, restauração assistida e adaptadores PostgreSQL/MySQL/Redis/MinIO continuam pendentes.
- O banco SQLite deve permanecer em disco local, com uma instância gravadora por instalação. Bases Windows e Docker diferentes não se sincronizam automaticamente.

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

[Contrato da API](docs/API.md) · [Arquitetura e análise](docs/ANALISE_E_PROPOSTA.md) · [Validação funcional inicial](docs/VALIDACAO.md)
