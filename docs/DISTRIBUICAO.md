# Distribuição da Escritura Integrada

A aplicação tem o mesmo núcleo e a mesma interface nas distribuições Windows e Docker. Empresas, regras, importadores, relatórios e validações pertencem a uma única aplicação.

## Guias atuais

- [Windows: aplicativo gráfico, tray, pacote portátil e evidências do smoke](DISTRIBUICAO_WINDOWS.md).
- [Docker: produção, desenvolvimento, GHCR, perfis de infraestrutura e pacote offline](DEPLOY.md).
- [CI/CD: SemVer, main/develop, releases, concorrência e limpeza de caches](CI_CD.md).

Use os pacotes da [release estável](https://github.com/codisplanfiscalai/escritura-integrada/releases/latest) ou da [pré-release contínua](https://github.com/codisplanfiscalai/escritura-integrada/releases/tag/develop). Cada distribuição aprovada contém identificação da versão, commit, checksums e evidências dos jobs correspondentes. O histórico está em [GitHub Actions](https://github.com/codisplanfiscalai/escritura-integrada/actions).

## Comportamento por ambiente

| Aspecto | Windows | Docker |
|---|---|---|
| Entrada do usuário | `EscrituraIntegrada.exe`, com janela gráfica | Navegador, na porta da aplicação |
| Administração | Tray: abrir, iniciar, parar, reiniciar, configurar e sair | Docker Compose e healthcheck |
| Serviço Windows obrigatório | Não | Não se aplica |
| Runtime | Python, Qt/WebEngine e interface no ZIP | Imagens GHCR; dependências dentro das imagens |
| Dados | Diretório local do perfil, configurável | Volume persistente do ambiente |
| API e interface | Mesma origem local, porta em loopback | Mesma origem; apenas uma porta publicada |
| Banco atual | SQLite local | SQLite em volume local |
| Iniciar minimizado | Preferência no aplicativo | Não se aplica |

Instalações diferentes mantêm bases separadas. O desktop não sincroniza automaticamente com um container. PostgreSQL, MySQL, Redis e MinIO são imagens opcionais de infraestrutura; a presença delas não implica adaptadores ativos no núcleo.

## Evidência e limites

O smoke Windows executa o programa extraído do ZIP, verifica saúde, renderização básica e encerramento. O smoke Docker verifica inicialização, arquivos da interface, autenticação inicial, persistência e os serviços opcionais. A validação offline inclui exportação, carregamento e execução com `--pull never`.

Esses gates comprovam os comportamentos registrados em seus relatórios. A revisão dos fluxos operacionais está documentada na [validação funcional inicial](VALIDACAO.md), e a homologação com dados reais do escritório continua necessária. Uma definição de workflow por si só não comprova que um build foi aprovado: consulte a conclusão do run e os manifestos da versão utilizada.
