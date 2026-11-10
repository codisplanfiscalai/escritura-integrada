# Plano de cadastros globais e modelos fiscais

Status: proposta futura, não implementada. Esta entrega apenas documenta o desenho; não migra cadastros, não altera lançamentos e não publica regras fiscais. Inspeção do código local em 10/11/2026.

## Estado atual verificado

- **CFOP e associações** consulta a referência oficial compartilhada em `app/data/cfop-confaz-20261109.json`, permite copiar/editar CFOPs da empresa e mantém associações original → escrituração por empresa, sentido, modelo e vigência. O código original permanece preservado.
- **Classificações fiscais** edita `catalogs` da empresa: CFOP, NCM, receita e serviço. Seus CFOPs são os mesmos cadastros locais exibidos no outro menu. Há sobreposição de interface.
- **Plano de contas** é local à empresa: contas, propriedades, metadados e lotes. O plano padrão é copiado, não compartilhado. Não existe seletor global/próprio. Referências a `0050` em testes/documentação não demonstram plano global operacional nem validam a integralidade do plano fornecido.
- **Alíquotas** não existem no cadastro CFOP. Existem em regras separadas com fonte, responsável, versão, regime, UF, município e vigência. A pré-apuração exige seleção explícita de documentos/itens, base, efeito débito/crédito, fundamento e regra conferida compatível; grava memória e detecta alteração posterior. Não infere incidência apenas pelo CFOP.
- **Modelos reutilizáveis** já existem em `templates`: são snapshots de regras selecionadas de uma empresa de origem. A listagem depende de acesso a essa empresa. Aplicar um modelo copia regras para a destinatária como rascunho, sem responsável, para revisão local. Não é uma biblioteca global independente de empresas. Não há fluxo direto de derivar modelo de outro, versionamento de modelos, filtro estruturado de atividade, nem pacotes completos de apuração por segmento. Regime, UF e município já existem nas regras.
- **Produtos** importados usam `master_id` da empresa e identidade de origem emitente + código, separada por produto/serviço. Não existe equivalência canônica fornecedor → SKU próprio. Compras e vendas do mesmo produto podem ter IDs diferentes corretamente.

## Desenho proposto, ainda não implementado

### 1. Catálogos globais e organização dos menus

Centralizar CFOP e códigos de serviço em catálogo global versionado, com fonte, vigência e auditoria. Serviços precisam identificar tabela/sistema e município quando aplicável: códigos iguais não garantem mesmo significado. Consolidar a manutenção CFOP e deixar **Associações de importação** como configuração específica da empresa. Separar referência oficial de descrição ou parâmetro editorial; não sobrescrever texto oficial silenciosamente.

Adicionar alíquotas informativas editáveis por tributo, contexto e vigência, sem conexão automática com o motor de cálculo. Informar explicitamente na interface que não são regra de incidência nem autorização de crédito. Qualquer uso operacional exige regra específica conferida, compatibilidade e vigência.

### 2. Plano global padrão e cópia própria

Criar entidade de plano e versões publicadas. Validar e carregar o plano fornecido, incluindo 050, como plano global padrão. Na empresa, permitir **Usar plano global** ou **Duplicar como plano próprio**. A cópia conserva origem/versão e aceita adaptações independentes. Alterações globais futuras não reclassificam movimentos históricos automaticamente.

Preservar IDs e referências históricas. `journal_lines` hoje referencia `(company_id, account_id)`; remover o escopo da empresa ou compartilhar IDs diretamente quebraria a integridade. Projetar vínculo explícito conta local histórica ↔ conta/versão do plano e migração aditiva revisável. Empresas existentes com contas próprias não devem ser reassociadas sem conferência. Validar máscaras, hierarquia, acessos, classificadores e metadados Prosoft antes de publicar o 050.

### 3. Biblioteca global de tributação e apuração

Evoluir os modelos atuais para biblioteca global independente da empresa de origem, com permissões próprias, versões imutáveis, linhagem e ações **Criar modelo**, **Criar baseado em outro** e **Aplicar cópia à empresa**. Não copiar documentos, bases, participantes ou cenários reais entre empresas.

Cada modelo deve declarar: finalidade, regime, atividade/CNAE ou segmento, jurisdição, início/fim de vigência, tributos abrangidos, hipóteses de aplicação, exclusões, fontes verificadas, responsável pela revisão e estado rascunho/conferido. Regras devem detalhar enquadramento e exceções necessários, não apenas CFOP. Cenários reutilizáveis devem conter estrutura e critérios de apuração, nunca valores ou conclusões de outra empresa.

Aplicar uma versão cria cópia local adaptável, rastreando modelo/versão de origem e alterações locais. Manter o comportamento seguro atual de exigir revisão da cópia antes do uso. Revisar regime, atividade, UF/município, vigência e eventuais conflitos com regras existentes; apresentar prévia e bloquear ambiguidades. Atualizar modelo global não altera a cópia local nem apurações anteriores. Oferecer comparação e adoção explícita de nova versão.

Exemplos de organização futura, sem parâmetros tributários presumidos:

- **Simples Nacional**: separar regime, atividades, segregações e requisitos de apuração. Não apresentar o cálculo atual base × alíquota como apuração completa do DAS; anexos, receita acumulada e demais condições exigem suporte específico e revisão.
- **Regime normal**: esclarecer o escopo estadual e o regime federal aplicável, sem tratar “normal” como sinônimo único de Lucro Real ou Presumido.
- **Farmácia**: modelo de atividade combinável com o regime efetivo. Eventuais tratamentos por produto, monofásicos ou de substituição tributária só entram com enquadramento, fonte, jurisdição e vigência verificados. Não aplicar a todos os itens pela descrição “farmácia”.

### 4. Identificação de produtos para futura conciliação

Manter `master_id`, emitente, código e conteúdo original. Acrescentar mapa explícito entre produto do fornecedor e produto canônico/SKU próprio, com unidade, fator de conversão, vigência, evidência e responsável. NCM, descrição e código de barras podem sugerir candidatos, mas não autorizam fusão automática. A conciliação futura deve conseguir rastrear cada venda e compra até seus itens originais.

## Sequência segura e critérios de aceite futuros

1. Validar fontes/carga 050 e desenhar contratos de dados e permissões globais antes de migrar.
2. Implementar entidades e migração aditiva, com prévia de conflitos, backup e testes de preservação das referências existentes.
3. Consolidar menus e seletor de plano; manter associações e adaptações específicas isoladas por empresa.
4. Implementar versões/derivações dos modelos e cópias locais com revisão obrigatória.
5. Testar que nenhuma edição global, alíquota informativa ou mera escolha de CFOP gera tributo, crédito, contabilização ou alteração retroativa; testar incompatibilidade de regime/atividade/jurisdição/vigência, acesso entre empresas e rastreabilidade dos itens.

## Código inspecionado

- `frontend/src/App.vue`, `frontend/src/views/CfopView.vue`, `frontend/src/views/SettingsView.vue`.
- `app/cfop.py`, `app/core.py` (`catalogs`, regras e `templates`), `app/db.py`, `app/migration_v3.py`.
- `app/account_plans.py`, `app/account_plan_codec.py`, `app/data/account-plan-default.json`.
- `app/tax_assessment.py`, `app/cadastros.py`, `tests/test_account_plans.py`, `tests/test_import_masters.py`.
