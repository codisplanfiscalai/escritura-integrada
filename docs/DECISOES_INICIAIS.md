# Escritura Integrada — decisões antes da implementação

Data: 06/11/2026. Versão de trabalho: 0.4.0-dev.1.

Nova aplicação independente, sem modificar os sistemas de referência. Monólito modular Python/FastAPI + Vue 3. Uma interface operacional, sem iframe legado ou páginas Markdown como telas. Windows: aplicativo gráfico com tray e backend local em thread, sem serviço; Docker: mesma API e UI. Nesta versão o armazenamento é SQLite transacional em disco local com WAL; execução única por banco. PostgreSQL/multi-instância exige migração e validação futuras, não será anunciado como pronto.

Contexto global visível de empresa e competência; cada modal captura contexto imutável; mudança de empresa com edição pendente exige descarte explícito ou retorno à edição. Edição cadastral não implica ativação. Empresa é argumento obrigatório em todas as operações e relações são verificadas no servidor.

Transações, centavos/Decimal, versões otimistas, idempotência, auditoria e fechamento fiscal/contábil independente. Nenhuma alíquota ou regra fiscal será inferida dos binários. Regras configuradas têm vigência, fonte e responsável; cálculo paramétrico não equivale a apuração legal homologada.

Navegação: Visão geral; Empresas; Documentos; Importações; Contabilidade; Financeiro; Conciliação; Livros e relatórios; Parâmetros; Competências. Guias simultâneas, modais agrupados, cinza claro/azul petróleo, ícones vetoriais, ESC e confirmação de alterações não salvas.

Referência V4: CTB020900, print image(20261106-041236).png, versão5.92.0.0. Filtros e despacho TXT/CSV/OFX/QIF/OFC comprovados estaticamente; leitores não homologados em execução. CTB020900A5.42 tem finalidade distinta de conciliação de lançamentos/origem/baixa.

Validação prioritária em navegador real: criar A, editar A sem alterar empresa ativa, ativar A, lançar, ativar B, garantir isolamento e retornar a A. Testes negativos de IDs cruzados, período fechado, duplicidade e desequilíbrio; inspeção visual 1366×768, 1650×900 e móvel. Dados demonstrativos identificados e sem dados reais dos prints.
