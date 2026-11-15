# Prosoft: interface, escolha dos layouts e mapeamentos por empresa

Este incremento depende da PR40 (`5b528cdd06e9b267187f905695c7ec75ebae7bf9`). Acrescenta a operação pela interface e configurações persistentes aos exportadores já existentes. Não implementa os layouts restantes nem comprova aceite dos arquivos na instalação Prosoft.

## Escolhas disponíveis

No módulo **Fiscal → Exportação Prosoft fiscal**, o campo **Tipo de exportação Prosoft** permite escolher notas de entrada, notas de saída ou ambas. As notas dos modelos 55/65 continuam com a cobertura parcial de campos descrita no [contrato do exportador](EXPORTACAO_PROSOFT_INCREMENTO.md). Somente os TXT correspondentes às direções escolhidas entram no ZIP. Documentos de outro tipo permanecem na prévia/manifesto com o motivo “Tipo/layout não selecionado”; não são apagados.

No módulo **Contábil → Integração Prosoft**, o mesmo campo permite escolher **Lançamentos contábeis (LC1/LC2)** ou **Lançamentos e contas ausentes (LC1/LC2 + CTA)**. LC1 e LC2 são partes do perfil de lançamentos, não arquivos independentes escolhidos arbitrariamente. No segundo perfil, cada conta movimentada que deve gerar CTA precisa ter a opção de cadastro marcada e os campos cadastrais conferidos. Escolher o primeiro perfil exclui CTA sem apagar suas definições salvas.

**SPED é uma ferramenta interna separada.** A exportação Prosoft usa os layouts próprios de importação do destino. Um arquivo produzido pela ferramenta SPED pode servir a outras aplicações, mas isso não transforma SPED em sinônimo destes perfis Prosoft.

A escolha do tipo, a empresa e o plano do destino, além dos mapeamentos, são salvos separadamente para cada empresa e área fiscal/contábil. O plano de conferência padrão continua 050 (`0050`), com outro plano aceito por escolha explícita. Não altera o plano ativo nem o cadastro remoto. Confira o mesmo plano ao importar: esses arquivos não têm campo de plano.

## Operação

1. Escolha a empresa e o exercício de trabalho. Ajuste a competência de **escrituração** da exportação; a emissão original continua separada.
2. Escolha o tipo de exportação próprio Prosoft. Os demais layouts recebidos aparecem como pendentes em “Outros layouts recebidos e limites de cobertura”.
3. Informe e confira empresa/plano do destino e os mapeamentos. No fiscal, espécie é o código cadastrado no Prosoft, não um código inferido do modelo. No contábil, contas, centros e terceiros mantêm confirmação própria.
4. Use **Salvar mapeamentos nesta empresa** para reutilizar em outra sessão/competência. A interface indica a versão salva e uma edição ainda não salva. Também é possível preparar uma prévia com os campos editados sem persistir essa edição.
5. Gere a prévia. Confira totais, cobertura, origens, não exportados, avisos e conversões ASCII. Avisos fiscais não viram travas de incidência/crédito. Confirme o destino e, quando necessário, aceite as conversões textuais para preparar o lote.
6. Baixe o ZIP fiscal ou TXT contábil. O lote local é imutável e idempotente. **Reimportar o mesmo arquivo no Prosoft pode duplicar movimentos**, pois o aplicativo não controla a base de destino.

O fiscal informa os totais de entradas e saídas, notas/registros, não exportados e avisos por linha. A origem e os motivos são mostrados até os primeiros 100 registros por seção, com o limite indicado; a API preserva a prévia completa, e o manifesto fiscal do download contém toda a trilha, sem truncar a exportação.

O contábil filtra inicialmente as contas movimentadas no mês. A busca e a opção para mostrar outras contas permitem preparar mapeamentos adicionais, em páginas de 100 contas. Contas não movimentadas nem abertas para edição não são expandidas automaticamente em milhares de mapeamentos vazios. Aliases globais também podem ser configurados. Dados de centros/terceiros são obtidos pelos serviços já autorizados de cadastros/lançamentos; não há novo espelhamento do plano.

CTA é cadastral: após criar a conta na importação de destino, desmarque a inclusão CTA dessa conta e salve. O aplicativo não sabe se a conta passou a existir na instalação Prosoft. TRC e SLD permanecem fora da saída, inclusive quando há terceiros nos lançamentos.

## Persistência, referências e permissões

As rotas usam sessão, CSRF e contexto transacional existentes:

| Operação | Contábil | Fiscal | Permissão |
|---|---|---|---|
| Consultar configurações | `GET /prosoft/settings` | `GET /prosoft-fiscal/settings` | `accounting.prosoft:read` / `fiscal.prosoft:read` |
| Salvar configurações | `PUT /prosoft/settings` | `PUT /prosoft-fiscal/settings` | `accounting.prosoft:edit` / `fiscal.prosoft:edit` |
| Prévia/confirmação/download | Rotas da PR40 | Rotas da PR40 | `export` da área correspondente |

Os caminhos são relativos a `/api/companies/{cid}`. PUT recebe `{ "version": 0, "settings": {...} }`; GET/PUT retornam `company_id`, `mode`, `version`, `settings` e `unavailable_accounts`. A gravação atualiza uma linha por empresa/área no cadastro existente `masters`, com tipo interno `prosoft_export_settings`, e um evento de auditoria atômico. Não há mudança de schema nem criação de tabela. O tipo interno não é aceito nas rotas genéricas de edição de cadastros.

A configuração contém `company_code`, `plan_code` e `record_types`, além de `batch/accounts/centers/participants` no contábil ou `species/cfop_accounts` no fiscal. Os valores de `record_types` são:

```json
{"record_types": ["incoming_notes", "outgoing_notes"]}
```

ou somente uma dessas direções no fiscal; no contábil:

```json
{"record_types": ["LC1", "LC2"]}
```

com `"CTA"` opcional. Tipos repetidos, desconhecidos, seleção vazia e CTA/LC2 isolados são recusados como perfil inválido. A ordem é normalizada. A API anterior continua funcionando quando `record_types` é omitido: ambas as direções fiscais e CTA apenas para contas marcadas no mapeamento, conforme o contrato da PR40. Sem seleção explícita, os bytes do arquivo fiscal legado não ganham metadados novos de seleção.

A interface envia os mapeamentos explícitos e `settings_version` na prévia e na confirmação. A versão é revalidada dentro da transação do exportador. Se outra sessão salvar configurações, a exportação com versão anterior recebe `409 stale_settings`, mesmo se ainda houver uma prévia aberta. Chamadas anteriores da API que enviam mapeamentos explícitos sem `settings_version` continuam válidas; a configuração salva não é aplicada implicitamente a esses clientes.

As referências contábeis salvas usam identidade global imutável ou ID local da empresa, resolvidas pelos serviços existentes. Quando um alias negativo ganha ID operacional positivo, a configuração volta associada à mesma conta, sem alocação/cópia de conta no ato de salvar. Outra versão de plano com acesso igual não herda o mapeamento: referências indisponíveis são preservadas e indicadas separadamente, sem reassociação por nome/acesso. Rascunhos da interface também acompanham essa materialização de identidade.

Configurações são metadados reutilizáveis por empresa: salvá-las em competência fechada não reabre o mês nem altera escrituração. Os serviços existentes continuam protegendo alterações fiscais/contábeis. Ler configurações, preparar prévia e navegar não grava movimentos. A confirmação grava somente lote e auditoria; os dados econômicos permanecem intactos.

## Contexto e edições simultâneas

Alterar campos ou tipo de exportação remove a prévia, a confirmação e o link de download exibidos. Alterar competência, exercício ou módulo invalida requisições antigas; seus resultados tardios não substituem o contexto atual. Os rascunhos da mesma empresa permanecem entre competências/exercícios e navegação. Trocar de empresa limpa os campos anteriores e carrega os da empresa escolhida. Recarregar a página ou descartar a guia elimina rascunhos ainda não salvos; a configuração persistida permanece.

Salvar usa versão esperada e transação: duas sessões com a mesma versão não sobrescrevem uma à outra. Conflitos mantêm o rascunho local e exigem uma decisão explícita de **Recarregar salvos e descartar edição** antes de substituir os campos. As respostas de load, save, preview e confirm são descartadas após troca de contexto ou desativação da guia. Os botões de exportação dependem de `export`; salvar depende de `edit`. Conceder somente leitura não concede essas ações. Usuários antigos com permissões específicas precisam receber a ação `edit` para salvar.

## Inventário dos layouts recebidos

Conferência estrutural dos dois PDFs e dos três modelos Excel do `Prosoft.zip` fornecido. Foram lidos os títulos das seções/posições dos PDFs e somente os cabeçalhos das planilhas padrão, sem usar valores privados como fixtures. “Pendente” significa que este exportador não emite o layout, mesmo que outros módulos possuam funções relacionadas. Não foi executada importação real de nenhum deles no Prosoft.

| Material e tipo | Referência conferida | Situação neste exportador |
|---|---|---|
| Notas de entrada | PDF fiscal, pp. 1–7, 2340 posições | Disponível parcialmente; escolha explícita na interface |
| Notas de saída | PDF fiscal, pp. 11–17, 2611 posições; observações p. 18 | Disponível parcialmente; escolha explícita na interface |
| Mapa Resumo ECF | PDF fiscal, pp. 22–25 | Pendente |
| Itens de notas de entrada | PDF fiscal, pp. 27–34 | Pendente |
| Itens de notas de saída | PDF fiscal, pp. 38–45 | Pendente |
| Inventário TXT | PDF fiscal, p. 48 | Pendente |
| RCPE | PDF fiscal, p. 49 | Pendente |
| Produtos | PDF fiscal, pp. 50–53 | Pendente |
| Faturas | PDF fiscal, pp. 56–57 | Pendente |
| Itens de cupom fiscal | PDF fiscal, pp. 58–59 | Pendente |
| Serviços prestados SP | PDF fiscal, pp. 60–65 | Pendente |
| Serviços tomados SP | PDF fiscal, pp. 73–78 | Pendente |
| Serviços prestados BA | PDF fiscal, pp. 88–91 | Pendente |
| Serviços prestados outros municípios, versão 1 | PDF fiscal, pp. 98–101 | Pendente |
| Serviços prestados RJ | PDF fiscal, pp. 109–111 | Pendente |
| Valores avulsos para integração | PDF fiscal, p. 117 | Pendente |
| Itens de faturas | PDF fiscal, p. 118 | Pendente |
| Meios de pagamentos | PDF fiscal, p. 119 | Pendente |
| Serviços — redução BC IBS/CBS | PDF fiscal, p. 120 | Pendente |
| Chave de acesso complementar | PDF fiscal, p. 121 | Pendente |
| CTA | PDF CTBLCTOS, p. 2, 208 posições | Disponível, como complemento opcional de contas movimentadas ausentes |
| TRC | PDF CTBLCTOS, pp. 3–4 | Pendente; resolver ambiguidades de CPF e sobreposição 501–508 |
| LC1/LC2 | PDF CTBLCTOS, pp. 4–5, 448/342 posições | Disponíveis, perfil de lançamentos |
| SLD | PDF CTBLCTOS, p. 6 | Pendente; definir exercício/saldo/movimentos e reaplicação para evitar dupla contagem |
| Modelo Excel de plano de saúde R4010 | 13 cabeçalhos: operadora/CNPJ/ANS, beneficiário/dependente, valores e reembolsos | Pendente neste módulo; não equivale à emissão de evento oficial |
| Modelo Excel de contas a pagar/receber | 20 cabeçalhos: tipo, integração, fatura, contraparte, datas, bruto/líquido, baixas, encargos e processo | Pendente neste exportador; títulos existentes não são convertidos automaticamente |
| Modelo Excel de inventário | 17 cabeçalhos: produto/unidade/NCM/situação, terceiro, quantidade/valores e ICMS/ST/FCP | Pendente neste exportador |

Os nomes dos modelos Excel são `PlanoDeSaudeR4010ModeloPadrao.xlsx`, `ContasPagarReceberModeloPadrao.xlsx` e `InventarioModeloPadrao.xlsx`. Nenhum modelo recebido foi copiado para a PR. A planilha de acompanhamento de homologação e o pacote privado continuam referências externas, sem dados transpostos para exemplos publicados. Nenhum módulo SPED, contabilização diária, desempenho, Docker ou produção é alterado por esta frente.

## Validação

A descoberta existente do CI inclui os testes novos de backend e frontend. O workflow também executa `scripts/browser_prosoft_export.py` e coleta apenas artefatos produzidos por esse ensaio sintético. A base encadeada `feat/prosoft-fiscal-accounting-increment` foi adicionada ao gatilho de pull request; permissões de CI continuam `contents: read`, sem etapa de release/deploy.

Comandos locais:

```bash
PYTHONPATH=tests:. python -m unittest test_prosoft_settings test_prosoft_increment -v
node --test frontend/tests/*.test.js
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build
PYTHONPATH=. python scripts/browser_prosoft_export.py
python -m compileall -q app/prosoft.py app/prosoft_fiscal.py app/prosoft_profiles.py app/prosoft_settings.py app/business.py app/business_api.py app/permissions.py scripts/browser_prosoft_export.py tests/test_prosoft_settings.py
git diff --check
```

Neste ambiente, as dependências DANFE da aplicação foram disponibilizadas no `PYTHONPATH` por diretório temporário já existente. O navegador local foi o Chromium Headless Shell 141 já instalado, selecionado por `ESCRITURA_TEST_BROWSER`; o Chromium comum não iniciou por restrição de socket do ambiente. Não houve alteração de requisitos/locks. O teste usa servidor local, SQLite descartável, contas/terceiros/documentos fictícios, arquivos sintéticos e fechamento válido de competência sem documentos pendentes.

Validação final:

- **354 testes de backend passaram em 137,555 s**, em 24 módulos: 12 testes novos e 342 regressões, incluindo a cobertura da PR40, permissões/contexto, plano compartilhado, reprocessamento, retenção de pacotes e infraestrutura/CI. Os novos cenários incluem persistência/isolamento/reinício do serviço, seleção de layouts, versões, concorrência, rollback da configuração/auditoria, fechamento preservado, referências de outra empresa, aliases e API legada.
- **154 testes de frontend passaram**, sendo 16 novos em relação à base, com a regressão de competência anterior adaptada ao componente real. Testam snapshots de payload, tipo escolhido, rascunhos, conflitos, respostas tardias de load/save/preview/confirm, empresa/mês/exercício/módulo, navegação, materialização de alias e preparação de um plano sintético de 10 mil contas sem expandir todas em mapeamentos vazios.
- **Build Vite passou**, com o aviso preexistente de chunk acima de 500 kB. Sintaxe de nove arquivos Python, YAML e `git diff --check` passaram; não há lint configurado no repositório.
- **Chromium 141.0.7390.37 integrado passou**: persistência após reload, isolamento entre duas empresas, entradas/saídas/ambas, perfil contábil com/sem CTA, contas/terceiros/centros, totais e avisos/não cobertos, confirmação/download real de ZIP/TXT, posições e replay, mudança de campos, prévia pendente durante troca de empresa e exercício F8, desktop 1440 e mobile 390 com controles dentro do viewport e tabelas roláveis, competência fechada e hashes de dados econômicos preservados. Sem erros JavaScript de página. Evidências são geradas em `artifacts/browser-prosoft-export/`; não são arquivos privados fornecidos pelo usuário.
- As primeiras tentativas do ensaio identificaram rótulos ambíguos, captura móvel cortada e seletores de teste dependentes de avisos transitórios; foram corrigidos e o cenário completo foi repetido com sucesso. O fechamento usa empresa sintética sem documentos pendentes, respeitando a regra existente em vez de desabilitá-la.

Não executados: suíte integral do aplicativo, PostgreSQL operacional, validação de escala/concorrência real, outros navegadores, Prosoft/PVA/Windows, novos binários/instaladores/imagens ou produção. O teste de 10 mil contas é de estado da interface, não benchmark nem prova de desempenho da exportação ou do servidor. Permanece ausente o acesso confirmado à instalação Windows/RDP/Prosoft para um ensaio de importação. A interface e os testes internos não comprovam homologação do destino. Nenhuma base real, transmissão, encerramento fiscal, merge, release ou implantação foi executada.
