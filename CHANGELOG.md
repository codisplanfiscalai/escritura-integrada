# Histórico de alterações

As releases e pré-releases publicadas possuem versão, commit de origem, manifesto e hashes. A referência contínua `develop` contém apenas a pré-release atual; as versões estáveis preservam suas tags `vX.Y.Z`.

## 0.8.0 — em desenvolvimento

- Limpeza integral dos movimentos do módulo em uma operação, com prévia automática e confirmação simples; movimentos protegidos por períodos/dependências são preservados. Tabelas fiscal e contábil até 5.000 registros por página e Excel de todos os resultados pesquisados, além da página atual.

- Relatórios: 17 modelos contábeis/fiscais específicos, catálogo de evidências, prévia PDF maximizável, folha inicial e exportações vinculadas aos filtros gerados. Saldos do Razão pesquisado preservados e filtros de apuração incompatíveis rejeitados. Os modelos não certificados são identificados sem alegar identidade Prosoft. [Cobertura e validação](docs/RELATORIOS_E_MODELOS.md).

- Operações individuais/em lote fiscais e contábeis, com exclusão física transacional, prévia/consentimento, períodos e dependências, conferência/escrituração fiscal e alterações restritas. [Operação e limites](docs/OPERACOES_EM_LOTE.md).

- Plano contábil genérico de 73 contas; importação/exportação JSON nativo e Prosoft (exportação 204 e importação P/C), com prévia, originais preservados, conflitos e referência sem ativação. [Operação e limites](docs/PLANO_CONTAS_INTERCAMBIO.md).

- Carga padrão dos relatórios CFOP enviados: 779 registros, textos e parâmetros preservados, comparação com o CONFAZ e importação por empresa sem ativação tributária. Detalhes e limites em [Carga CFOP](docs/CFOP_CARGA_REFERENCIA.md).

- Referência CFOP do Anexo II do CONFAZ: 619 códigos, notas explicativas e redações com vigência; cópia para a empresa preserva cadastros existentes.
- Associações explícitas por empresa, sentido, modelo e vigência; CFOP original preservado.
- Importação fiscal com preparação e escrituração direta do lote selecionado, sem títulos ou partidas implícitos.
- Edição motivada da escrituração sem efeitos vinculados, com histórico, bloqueios e preservação das correções na reimportação.
- Conferência posterior da importação direta e cobertura de testes HTTP, navegador e recursos nos pacotes.
- Escopo e limites: [escrituração fiscal 0.8](docs/ESCRITURACAO_FISCAL_0_8.md).

## 0.4.0

- Aplicação integrada com área de trabalho Vue, empresa ativa e competência explícitas.
- Cadastro e edição de empresas, documentos e partidas com contexto conferido no servidor.
- Importadores com prévia e confirmação, baixa parcial, conciliação e relatórios internos.
- Fechamentos fiscal e contábil independentes e auditoria.
- Aplicativo Windows com janela, tray, administração local e empacotamento portátil x64.
- Pipeline SemVer para `main`/`develop`, release estável e pré-release contínua única.
- Imagens GHCR da aplicação, base e infraestrutura, com ambientes Compose separados e somente a porta da aplicação publicada.
- Pacotes de distribuição, smokes, manifestos e manutenção de caches do Actions.

O status de build e publicação deve ser consultado no run associado. Esta versão não declara homologação tributária ou integração Prosoft completa.
