# Cadastros globais — implementação local

O menu **Cadastros** reúne **Empresas**, **Terceiros**, **Contadores** e **Vínculos locais de terceiros**. Produtos e serviços continuam no Fiscal e pertencem à empresa. Estabelecimentos continuam locais, sujeitos à validação de raiz do CNPJ já existente.

Empresas reutiliza a tela `CompaniesView` e as rotas existentes. Abrir ou fechar sua guia não muda empresa, módulo ou competência ativos. Continua disponível sem empresa selecionada, mas a listagem permanece filtrada pelas concessões do usuário; inclusão e edição mantêm as autorizações anteriores. Mover o menu não concede acesso a outras empresas.

## Consulta global e autorização

Terceiros e Contadores são catálogos da instalação. Uma empresa autorizada consulta o catálogo completo sem cadastrar vínculos previamente. A empresa ativa fornece o contexto de autorização, não um filtro por vínculo. Criar um registro global não cria masters nem altera dados empresariais.

A instalação (arquivo SQLite) é a fronteira de organização existente neste aplicativo. Não há tabela de organizações nem compartilhamento entre instalações. Organizações distintas devem continuar usando bancos separados. Esta mudança não transforma uma instalação em plataforma multiorganização.

A leitura de Terceiros usa a nova permissão **`fiscal.shared_parties:read`**. A permissão antiga `fiscal.masters` continua controlando exclusivamente os cadastros locais; ela não concede leitura global por si só. Contadores usam `accounting.accountants:read`. As rotinas aparecem na matriz existente. Concessões por módulo (`fiscal.*`, `accounting.*`) seguem as regras existentes; não há criação ou alteração automática de concessões pessoais ou de grupos.

A leitura global não concede acesso aos documentos, papéis, contatos privados, histórico ou cadastros locais de outras empresas. Os vínculos retornados são filtrados pela permissão de leitura local. Não são divulgados vínculos ocultos ou sua contagem.

A manutenção direta dos perfis globais (incluir, editar, desativar) exige administrador, seguindo o padrão dos outros catálogos globais do aplicativo. A autorização é revalidada na transação, além do middleware. Permissões de edição empresarial não se tornam autoridade global. As APIs legadas de cadastro/importação continuam indexando novos terceiros locais com os campos comuns permitidos; não sobrescrevem o perfil comum já existente.

## Uso na empresa

O botão **Usar nesta empresa** estabelece o vínculo necessário em uma única operação. Não exige escolher novamente a empresa nem digitar código. A consulta não chama essa operação e não produz efeitos no banco.

Para Terceiros, a operação exige leitura global e inclusão em `fiscal.masters` da empresa ativa. Quando ainda não existe vínculo, cria um master de uso com código `GLOBAL-<id>` (sufixo quando o código estiver ocupado), mantendo o ID do catálogo comum. Repetir a operação não duplica masters nem vínculos. O destino é obtido da rota/contexto, e não de um campo arbitrário enviado pelo cliente.

Para Contadores, a operação exige leitura e edição em `accounting.accountants` na empresa ativa e cria apenas a relação com o profissional global. Não cria master nem outra linha profissional.

Colisões com identidade local preexistente são recusadas para revisão, sem fusão ou sobrescrita. Registros globais legados ambíguos permanecem distintos. A manutenção manual não cria outra linha global com CPF/CNPJ já presente no mesmo tipo de catálogo. A identidade existente permanece imutável.

A sessão, o CSRF e o contexto são revalidados pelo middleware e pela transação existente. Versões impedem sobrescrita concorrente. A rota anterior `/links` permanece para compatibilidade; a interface usa `/use` no contexto ativo.

## Persistência e compatibilidade

`shared_registrations` contém o cadastro comum e `shared_registration_links` os vínculos de **uso**, não concessões de consulta. Contadores guardam CPF, nome, CRC, UF, categoria profissional, e-mail e telefone.

A migração é transacional, aditiva e idempotente. Cada participante legado recebe sua própria linha comum e vínculo, mesmo quando há outro registro com o mesmo CPF/CNPJ. Não são apagados ou unidos registros ambíguos. Nenhum ID de master, documento, título ou partida é substituído. Uma instalação anterior recebe backup antes de criar as tabelas novas. Esta revisão da consulta global não exige nova migração de dados nem modifica os vínculos existentes.

Somente campos comuns selecionados do legado são copiados: nome, identidade, nome fantasia e endereço/campos cadastrais. Contatos privados, papéis, notas e evidências de origem não são promovidos automaticamente. Uma edição do catálogo atualiza sua visão comum em todas as empresas autorizadas; **não sobrescreve os cadastros locais de uso nem os documentos históricos**. A tela de vínculos locais mantém os recursos anteriores de perfil, histórico, identidade e reutilização revisada.

A desativação é lógica, impede novos usos e preserva vínculos/documentos existentes.

## Verificação local

```sh
ESCRITURA_DATA_DIR="$PWD/artifacts/global-catalog-qa/bootstrap" PYTHONPATH=.:tests .venv-tests/bin/python -m unittest test_shared_registrations test_third_parties test_third_party_history test_core test_management test_import_masters test_fiscal_library -v
node --test frontend/tests/*.test.js
npm run build --prefix frontend
```

Fixtures exclusivamente sintéticas cobrem consulta global sem vínculos, uso sem permissão sobre a empresa de origem, idempotência, ausência de alterações em dados empresariais e permissões, CRUD administrativo, ocultação de vínculos locais, isolamento entre instalações e de produtos, documentos históricos, duplicidades, CSRF, concorrência, rollback e backup. O teste Vue monta a lógica real do componente e verifica envio duplicado e invalidação do contexto.

A prévia pelo script oficial respondeu HTTP 200 para a página e `/api/session` dentro da execução do servidor. O navegador cloud e uma execução separada receberam `ERR_CONNECTION_REFUSED` no mesmo endereço enquanto o servidor estava ativo. A inspeção visual segue pendente por esse limite de conectividade. Não foram usados túneis, serviços externos nem produção para contorná-lo.

## Revalidação da composição com develop dev.23

Base conferida: `67a5e2e0b3c65fe7948827d6d66da5361970bfb1`. A integração local preserva `ab0b691aefc35bac8ae471981fd2a2a4a5d44821` e mantém os mixins de Cadastros, configurações/exportação Prosoft e composição contábil fiscal. Nenhum workflow foi modificado por esta frente.

Resultado sobre essa composição: **142 testes Python**, **180 testes frontend**, build Vite, compilação Python e `git diff --check` aprovados. A suíte Python executada foi:

```sh
ESCRITURA_DATA_DIR="$PWD/artifacts/cadastros-synced-qa/bootstrap" PYTHONPATH=.:tests .venv-tests/bin/python -m unittest test_shared_registrations test_third_parties test_third_party_history test_core test_management test_workspace_context test_import_masters test_fiscal_library test_business test_fiscal_sales_composition test_prosoft_settings test_prosoft_reception_composition -v
```

Os três roteiros de navegador de evidência cadastral, desempenho e guias foram atualizados para os novos nomes de menu, preservando suas verificações. Essa atualização passou na compilação, mas os roteiros não foram executados nesta rodada; a inspeção visual permanece pendente pelo limite descrito acima. A suíte backend integral, PostgreSQL real, binários e imagens não foram reexecutados nesta composição.
