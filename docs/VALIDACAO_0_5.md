# Validação da expansão 0.5

Registro de 07/11/2026. A validação abaixo distingue código executado, evidência estática e homologação ainda necessária.

| Etapa | Execução comprovada | Limite |
|---|---|---|
| Contexto | MHTML integralmente extraído e lido; hashes conferidos dos 18 executáveis do ZIP; levantamento dos 281 formulários | Conversas apenas mencionadas/ligadas no MHTML não têm seu conteúdo recuperado; não houve execução dos legados |
| Núcleo | `python -m unittest discover -s tests -q`: **132 testes aprovados** | Fixtures sintéticas; não certificam cálculos tributários ou comportamento integral dos legados |
| Interface | **5 testes de datas aprovados** e `npm --prefix frontend run build` concluído | Build não substitui navegação no navegador |
| Cadastros e consultas | Testes de normalização, cache, fallback, IE distinta de isenção, revisão/versão e isolamento | Consulta real de CEP 01001000 concluída via BrasilAPI após indisponibilidade do ViaCEP; tentativa real de CNPJ não obteve resposta útil dos três provedores |
| Fiscal → financeiro → contábil | Testes de escrituração com modelo, parcelas, deduplicação, soma e reversão transacional | Apuração legal automática por regime/UF/município não implementada |
| Financeiro | Baixa com principal/juros/multa/desconto, reversão vinculada, renegociação e desfazimento; idempotência inclusive de baixas antigas | Renegociação não contabiliza encargos implicitamente |
| Conciliação | Vínculos e rateios, limite de valores, baixa explícita, desfazimento sem efeito financeiro oculto | Consulta por participante não reproduz todas as funções de conciliação do legado |
| Contabilidade/relatórios | Múltiplas partidas, saldos iniciais, estornos, recorte por centro, Balanço/DRE e contas não classificadas | Relatórios internos; sem ECD/ECF, encerramento automático ou consolidação entre empresas |
| Compactados | ZIP existente; 7z sintético; RAR3 sem compressão sintético; rejeição de corrupção, senhas, limites e caminhos | RAR comprimido e codecs reais dependem da distribuição e de homologação adicional |
| Prosoft | LC1 de 448 bytes e LC2 de 342 bytes; modos simples/detalhado, posições, limites, mapeamento e confirmação imutável | Sem execução na instalação Prosoft de destino; CTA/TRC/SLD e exportação fiscal pendentes |
| Controle | Permissões por empresa, fechamento independente, bloqueio de contexto, concorrência e migração aditiva | SQLite local; infraestrutura opcional não equivale a adaptadores implementados |

## Validação visual e distribuição

O Chromium local encontrou restrição de sockets e a prévia não ficou acessível pelo navegador compartilhado. A validação foi executada no runner GitHub, com Chromium 151.0.7922.34.

**Run aprovado:** [42338563297](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/42338563297), versão de conferência `0.5.0-pr.1.6`, commit de integração da PR `3451c2b69ec9e19e7e9b6b72a6d185649539475a` e código da branch `2fdbe79522ea277012a953893154a4afe1c65295`.

| Gate | Resultado |
|---|---|
| Linux, testes e interface | Aprovado: 132 testes Python, cinco testes de datas, build Vue e oito controles no Chromium |
| Windows x64 empacotado | Aprovado: suíte Windows, construção do executável, API, autenticação de demonstração, renderização Qt/WebEngine e encerramento sem processos remanescentes |
| Imagens Linux amd64 | Aprovado: aplicação/base e inicialização isolada de Redis, PostgreSQL, MySQL e MinIO; somente a aplicação publica porta |

O navegador percorreu login/contexto, edição de outra empresa, consulta CNPJ simulada com aplicação seletiva e múltiplas IEs, documento → conferência → lançamento + duas parcelas, baixa parcial com juros/desconto e estorno, importação CSV sem perda de sessão, download idêntico ao original e Balancete com acesso às partidas de origem. O teste detectou e motivou a correção do histórico financeiro que podia mostrar dados anteriores ao abrir imediatamente após a baixa.

Foram produzidas oito capturas e nenhum erro JavaScript. A página de relatórios não apresentou transbordamento horizontal em 1440, 1024 e 390 px; a área de trabalho usa rolagem vertical própria e tabelas com rolagem horizontal quando necessário. Essas resoluções não constituem validação de todas as telas em todos os dispositivos. [Capturas e relatório da PR](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/42338563297/artifacts/13559984560).

A publicação repete os gates na versão reservada da `develop`. As capturas passam a integrar `EscrituraIntegrada-<versão>-browser-evidence.zip`, com versão e commit conferidos e SHA-256 no manifesto. Os smokes do Docker, publicação GHCR e teste de carregamento offline têm relatórios próprios na [pré-release contínua](https://github.com/codisplanfiscalai/escritura-integrada/releases/tag/develop). O run de PR não equivale, sozinho, à comprovação de upload ou de carregamento do bundle offline.

## Homologação operacional necessária

1. Importar os arquivos CTBLCTOS sintéticos no ambiente Prosoft compatível e conferir lotes/contas/centros antes de dados reais.
2. Validar compactados e documentos representativos do escritório, com versões e codecs identificados.
3. Configurar e revisar regras tributárias com fonte, vigência, regime e responsável; pré-apuração paramétrica continua marcada `legal_validation=false`.
4. Validar contratos, cobertura de IE e limites dos provedores com credenciais do próprio escritório; o cadastro manual permanece disponível offline.
5. Exercitar os fluxos operacionais em cópia de base, incluindo diferenças de competência, permissões e fechamento.

Referências: [diagnóstico](DIAGNOSTICO_EXPANSAO_0_5.md), [matriz](MATRIZ_RASTREABILIDADE.md) e [operação](OPERACAO_0_5.md).
