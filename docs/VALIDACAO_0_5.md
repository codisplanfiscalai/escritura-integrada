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

O Chromium local não iniciou devido à restrição de sockets do ambiente. O navegador compartilhado também não alcançou o servidor da prévia. Não foram fabricadas capturas nem considerados esses testes aprovados.

Foi incluído `scripts/smoke_browser.py` nos workflows de PR e release para executar os fluxos de interface no runner, com relatório e capturas nas larguras 1440, 1024 e 390. O resultado do run e os artefatos serão registrados após a execução. As capturas também integram o pacote `browser-evidence.zip` da release, validado por versão e commit. Builds e smokes Windows/Docker da versão 0.5 também dependem desse run; a existência do workflow não comprova publicação.

## Homologação operacional necessária

1. Importar os arquivos CTBLCTOS sintéticos no ambiente Prosoft compatível e conferir lotes/contas/centros antes de dados reais.
2. Validar compactados e documentos representativos do escritório, com versões e codecs identificados.
3. Configurar e revisar regras tributárias com fonte, vigência, regime e responsável; pré-apuração paramétrica continua marcada `legal_validation=false`.
4. Validar contratos, cobertura de IE e limites dos provedores com credenciais do próprio escritório; o cadastro manual permanece disponível offline.
5. Exercitar os fluxos operacionais em cópia de base, incluindo diferenças de competência, permissões e fechamento.

Referências: [diagnóstico](DIAGNOSTICO_EXPANSAO_0_5.md), [matriz](MATRIZ_RASTREABILIDADE.md) e [operação](OPERACAO_0_5.md).
