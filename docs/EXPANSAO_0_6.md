# Expansão 0.6 — competências, acessos, fiscal e instalação

## Diagnóstico e continuidade

Base conferida: `develop` 51537872f8598af84d22b4544f75a4001f42f56f (0.5.0-dev.6); `main` 438ffd6f40f54e4255f35f19a8e495095683b7e9 (0.4.1). A versão estável não foi alterada nesta etapa. A versão de desenvolvimento permanece superior à estável.

A base já possuía importação com prévia e originais, escrituração integrada, baixas/estornos/renegociação, cadastros assistidos, relatórios e exportação contábil Prosoft LC1/LC2. As lacunas prioritárias eram: competências sem catálogo anual, autorização restrita a perfis gerais, navegação dispersa, distribuição Windows apenas portátil, ausência de macOS e de finalização/transporte de apuração e exportações Excel/PDF no servidor.

A reconstrução anterior do MHTML, os hashes dos 18 executáveis, o levantamento dos 281 formulários e os limites da recuperação permanecem em `DIAGNOSTICO_EXPANSAO_0_5.md`, `MATRIZ_RASTREABILIDADE.md` e `referencias/`. Não se presume que textos de ramificações e anexos apenas mencionados no MHTML estejam acessíveis. A presente ampliação é implementação nova orientada pelos pedidos do usuário; não é uma declaração de equivalência integral aos algoritmos legados.

## Fluxos implementados

### Exercícios e competências

- Catálogo por empresa, módulo e exercício, com janeiro a dezembro. Novos anos de 1900 a 2199 são cadastrados pela tela de competências, sem movimentação anterior nem fechamento de outros anos.
- Seleção, cadastro do exercício, fechamento e reabertura são ações distintas. Meses fechados continuam consultáveis; justificativa, usuário, data e versão controlam fechamento/reabertura.
- Fiscal, Contábil, Financeiro e Social têm estados independentes. A sessão lembra a seleção por empresa/módulo.
- Empresa, módulo e mês acompanham as requisições de gravação. Contexto alterado em outra guia ou versão concorrente provoca recusa, preservando os dados digitados. Efeitos fiscais, contábeis e financeiros validam seus próprios bloqueios.
- Social possui somente o controle de competências. Folha, vínculos trabalhistas, eSocial e obrigações adicionais não foram especificados nem anunciados como disponíveis.

### Acesso por empresa, grupo e usuário

O administrador gerencia usuários, grupos ativos/inativos, membros, empresas e ações por rotina. A tela de permissões efetivas mostra o resultado e a origem de cada decisão. Alterações relevantes são auditadas e revogam sessões afetadas.

Regra única, aplicada no servidor e refletida na navegação:

1. Administrador ativo administra todo o ambiente; o próprio administrador não pode desativar/rebaixar seu acesso corrente.
2. Bloqueio individual da empresa prevalece sobre qualquer grupo/concessão.
3. É necessário acesso à empresa por grupo ativo ou concessão direta. Uma ação concedida sem acesso à empresa não libera a empresa.
4. Bloqueio individual da ação prevalece; depois, concessão individual; depois, bloqueio de grupo; depois, concessão de grupo. Sem decisão, recusa.
5. Dentro do mesmo nível, bloqueio prevalece entre padrões `*`, `módulo.*` e rotina específica. Uma concessão individual pode ser exceção a bloqueio de grupo, nunca a bloqueio individual.

Permissões são independentes em cada empresa. Gerar títulos ou contabilização ao escriturar exige também as ações correspondentes no Financeiro/Contábil. Falha em qualquer efeito reverte a transação inteira. Consultas de rastreabilidade ocultam módulos sem direito de leitura. A administração de usuários/grupos é global e exclusiva dos administradores; não foi criada delegação administrativa por empresa.

### Fiscal

- Regras com vigência, fonte, responsável, regime, UF e município; seleção explícita dos itens para bases com diferentes CFOP/NCM; recusa de sobreposição para o mesmo efeito; centavos inteiros e arredondamento decimal HALF_UP.
- Memória de pré-apuração com documentos/regras/versionamentos, ajustes classificados e saldo anterior. Cenário sem bases exige confirmação explícita; não é inferido como isenção.
- Finalização após revisão integral; transporte automático somente do crédito finalizado do mesmo tributo, empresa e mês imediatamente anterior. IBS e CBS não se compensam entre si.
- Alterar bases com apuração finalizada exige reversão. Apurações dependentes devem ser revertidas da mais recente para a anterior. Fechamento fiscal impede a reversão; reabertura exige permissão e motivo. Finalizar não gera pagamento, obrigação acessória ou transmissão.
- Relatórios de documentos, entradas, saídas, itens, operações/CFOP, participantes, classificações/NCM, bases/tributos declarados, inconsistências e apurações. Filtros e totais, acesso às origens, PDF e Excel gerados no servidor, CSV e impressão.
- Tributo não informado permanece ausente; não vira zero. Agregações de itens não multiplicam o total do documento. Excel contém aba de centavos e protege textos que poderiam ser interpretados como fórmulas.

Os livros são auxiliares de conferência. Não substituem livros oficiais homologados, PVA, obrigações acessórias ou validação fiscal por regime/UF/município. A matemática e o fluxo foram testados; as alíquotas e os cenários legais de ICMS/IPI/ISS/PIS/Cofins/IBS/CBS não são certificados pelo software. Revisão cadastral de CNPJ também não comprova enquadramento.

### Instalação e atualização

Ver `DISTRIBUICAO_DESKTOP.md`: instalador Windows por usuário, programa separado dos dados, manutenção em cópia com backup e recuperação, migração de pasta portátil e desinstalação preservando os dados. macOS possui app e pacote nativos para Intel e Apple Silicon; mínimo declarado 15.0. O núcleo Python/FastAPI + Vue continua compartilhado com Docker.

Não há certificados de assinatura Authenticode/Developer ID ou notarização configurados. Teste local de instalação no runner não equivale à aprovação de um download pelo SmartScreen/Gatekeeper.

## Matriz desta etapa

| Requisito | Origem/evidência | Implementação | Validação exigida |
|---|---|---|---|
| Doze meses por exercício/módulo/empresa | Pedido atual, correção do seletor limitado | `migration_v3.py`, `periods.py`, `PeriodsView.vue` | Criar ano sem lançamentos; consultar fechado; bloquear escrita; independência entre módulos/empresas |
| Grupos e exceções individuais | Pedido atual; recurso novo (I) | `permissions.py`, `access.py`, `UsersView.vue`, `GroupsView.vue`, `AccessMatrix.vue` | Conflitos, ausência de grupo, escopo por empresa, sessões revogadas, efeitos indiretos e origem efetiva |
| Menus por área | Pedido atual; fluxos já existentes | `App.vue` e views específicas | Abrir cada rotina habilitada; atalhos/guias; tela restrita não aparece sem acesso |
| Apuração, ajustes, saldo e memória | LFSLIVROSAPUR/formulários + pedido; cálculo legado parcial (R/V) | `tax_assessment.py`, `tax_ledger.py`, `AssessmentsView.vue` | Itens/CFOP/NCM; saldo segregado; memória obsoleta; revisão e reversão em ordem |
| Livros e relatórios fiscais | LFSLIVROS + pedido; oficialização pendente (V) | `fiscal_reports.py`, `report_exports.py`, `ReportsView.vue` | Totais exatos, filtros, origem, ausência distinta de zero, PDF/XLSX/CSV |
| Instalar/atualizar/migrar ZIP | Pedido atual, continuidade do tray | `maintenance.py`, `setup.iss`, scripts Windows | Instalação/desinstalação reais; base antiga schema 2; backup, falha, processo aberto e retrocesso |
| macOS Intel/Apple Silicon | Pedido atual; recurso novo (I) | spec, `build_macos.py`, `smoke_macos.py`, `preinstall` | Jobs nativos separados, pacote instalado/reinstalado, app/tray/QtWebEngine/API e encerramento |
| Publicação única develop | Histórico/MHTML e workflows existentes | CI/release e `ci/artifacts.py` | Todos os gates; mesma versão/commit/hash; main preservada; Windows/Mac/Docker/offline |

## Validação e limites objetivos

A suíte de backend usa bases e cenários sintéticos, inclusive migração, conflitos, precisão monetária, isolamento e rollback. `scripts/smoke_browser.py` executa os fluxos na interface em 1440, 1024 e 390 px. Os jobs Windows/macOS instalam pacotes e abrem executáveis reais; seus JSONs, capturas, checksums e logs acompanham a publicação. O commit e o status do workflow, e não a presença destes scripts, comprovam a execução.

O smoke de atualização Windows instala o pacote novo, simula uma versão anterior no registro e reinstala preservando o conteúdo. A migração de banco 0.5/schema 2 é criada pelo código publicado anterior e testada separadamente. No macOS há instalação e reinstalação reais do mesmo pacote e primeira abertura de base schema 2. Isso não cobre todas as combinações históricas de binários, configurações ou versões de sistemas operacionais.

Pendências: homologação legal e livros oficiais por cenário; NFS-e XML nacional/municipal (cadastro manual permanece; o XSD de produção 1.01 não foi validado nesta etapa); ampliação dos registros SPED além da cobertura declarada; conciliação contábil completa distinta da financeira; layouts Prosoft adicionais e teste na instalação de destino; escopo Social; assinatura de distribuição; adaptadores PostgreSQL/MySQL e serviços Redis/MinIO. Estes últimos continuam imagens opcionais de infraestrutura, sem integração funcional ao núcleo SQLite.
