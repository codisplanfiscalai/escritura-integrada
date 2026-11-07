# Evidências de validação da expansão 0.6

Os testes usam dados sintéticos e perfis temporários. Não foram usados dados reais do escritório nem executados os 18 binários legados.

## Backend e interface

A rodada local final aprovou 166 testes Python e 5 testes de datas dos campos da interface; o build Vue aprovou. Inclui verificações de CFOP misto, fechamento de conexões SQLite, recuperação somente após o instalador sair e dos gates de instalação nativa. O relatório `linux-checks.json` da distribuição registra a contagem final e o commit exato testado.

Foram exercitados: grupos e concessões individuais; bloqueios por empresa; prioridade entre regras; sessão revogada após alteração; autorização dos efeitos indiretos; exercícios com 12 meses; seleção por empresa/módulo; fechamento/reabertura independente; consulta fechada e recusa de escrita; contexto mensal de títulos e baixas; cache cadastral sob sessão; rastreabilidade sem exposição de módulos não autorizados; precisão monetária; apuração segregada; itens selecionados; memória obsoleta; finalização/reversão; relatórios PDF/XLSX/CSV; backup, falha de migração e restauração.

O Chromium local foi impedido de iniciar pelo ambiente. A validação visual é realizada no Chromium real do GitHub Actions por `scripts/smoke_browser.py`, com capturas em 1440, 1024 e 390 px. O roteiro inclui login, editar empresa sem ativá-la, CNPJ com resposta simulada e revisão seletiva, documento → conferência → duas parcelas + lançamento, baixa parcial com juros/desconto e estorno, importação/conferência bancária, relatórios com origem, novo exercício, fechamento/reabertura, grupo/usuário pela interface, usuário restrito, finalização fiscal e downloads PDF/Excel. A simulação cadastral não comprova disponibilidade atual dos provedores públicos.

O PDF foi renderizado e inspecionado. A fonte Bitstream Vera distribuída com ReportLab é incorporada para manter acentuação e apresentação em diferentes sistemas. Excel preserva valores e inclui centavos; textos iniciados por operadores não são convertidos em fórmulas.

## Instalação Windows

O job Windows executa a suíte Python, constrói o ZIP, inicia o executável real e verifica API, interface, versão e encerramento. Em seguida compila o instalador Inno Setup e executa instalação nova, atualização/reinstalação, recusa com PID ativo, recusa de downgrade, migração de base produzida pela versão 0.5/schema 2, abertura gráfica instalada e desinstalação com preservação dos dados.

A versão anterior do programa é simulada no registro para o teste de atualização; o pacote antigo completo não é instalado. O banco portátil antigo é efetivamente criado pelo código publicado 51537872f8598af84d22b4544f75a4001f42f56f. O teste de aplicação aberta utiliza um bloqueio com PID ativo. Não substitui validação de todas as versões históricas, antivirus e edições Windows em uso no escritório.

## macOS

Os jobs separados `macos-15` (arm64) e `macos-15-intel` (x64) constroem bundles Mach-O nativos e verificam a arquitetura. Instalam/reinstalam o `.pkg` com o Installer, abrem a aplicação Qt/WebEngine, conferem API, interface, barra de menus e encerramento, além de backup e migração de base schema 2. O relatório registra a versão real do host.

O mínimo declarado é macOS 15.0. Não há evidência para macOS anterior, Rosetta ou pacote universal. Assinatura ad hoc não equivale a Developer ID/notarização. O caminho de download com quarentena/Gatekeeper não é homologado pelo teste do runner.

## Distribuição

A release exige todos os gates, versão/commit coerentes e checksums dos instaladores, pacotes macOS, ZIP Windows, frontend, imagens Docker e bundle offline. Relatórios e capturas são assets da pré-release. O sucesso da PR comprova validação; a entrega ao usuário exige também sucesso do workflow de release e existência dos assets.

Esta documentação descreve os cenários e seus limites. Consulte o resultado final na PR #2 e nos manifestos da publicação; scripts implementados e builds iniciados, isoladamente, não comprovam execução bem-sucedida.
