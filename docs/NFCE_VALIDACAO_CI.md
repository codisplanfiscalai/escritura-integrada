# Busca indexada de cancelamentos XML NFC-e

## Escopo e identidade preservada

Na confirmação XML, Core._create_document examinava extra_json de todos os documentos da empresa/direção/modelo a cada criação. O patch acrescenta ltrim(number,'0')=ltrim(?,'0') e índice de expressão não único com o mesmo prefixo. A comparação Python final de número/série/emitente continua igual; permissões, competência, cancelamentos, originais, transações e decisões de conflito não mudam. O índice não mescla documentos nem impõe unicidade.

Para número ASCII numérico, igualdade canônica implica igualdade após retirar zeros iniciais. Para os demais textos, igualdade canônica exige a mesma string. O filtro pode selecionar candidatos adicionais como 0A/A, descartados pela comparação existente. A competência continua fora da identidade; documentos de períodos distintos não são escondidos da verificação.

A fixture estritamente sintética nfce_identity_lookup_ficticio.json contém 22 linhas e 18 cenários: zeros, texto, Unicode, legado longo, série, empresa, modelo, sentido, emitentes conhecidos/desconhecidos, períodos distintos e marcador não confiável. Os testes comparam a consulta anterior com a consulta real extraída do AST e preservam todos os valores; testes de API cobrem conflitos/cancelamentos/idempotência/isolamento e migração do índice.

## Reprodução local pequena

Com dependências fixadas do projeto instaladas, usar banco temporário descartável e TMPDIR em um volume de trabalho com espaço disponível. Não usar dados, DSN ou certificados de cliente/produção. A seleção abaixo é a mesma preparada para esta composição (88 testes); não precisa dos artefatos volumosos do benchmark:

    PYTHONPATH=.:tests python -m unittest -v test_nfce_identity_contract test_nfce_identity_lookup test_book_cancellation test_fiscal_series test_fiscal_import test_sped_native_export test_sped_bookkeeping test_postgres_backend.PostgresConfigurationTests
    git diff --check

A suíte completa é python -m unittest discover -s tests -v. O gate Linux existente também verifica frontend, build, manifests e navegador. A seleção pequena não substitui esse gate.

## PostgreSQL e sockets: gates obrigatórios

O runtime do aplicativo continua SQLite. A infraestrutura PostgreSQL preparatória não traduz o SQL do Core nem integra as permissões em create_app; este patch não anuncia migração operacional.

PostgreSQL 17 documenta [ltrim(text,text)](https://www.postgresql.org/docs/17/functions-string.html) e [índices em expressões](https://www.postgresql.org/docs/17/indexes-expressional.html). Sintaxe documentada não substitui execução real. O método PostgresBackendTests.test_nfce_candidate_ltrim_index_preserves_identity_contract_and_raw_values, no arquivo já executado pelo gate, cria schema/tabela/índice descartáveis com números/séries/JSON TEXT, parâmetros nativos %s e compara os 18 casos com o controle anterior. Confere valores originais, índice criado e imutabilidade da função. Não força planner em tabela pequena nem mede throughput PostgreSQL.

No runner Linux autorizado, executar realmente os três testes de socket:

    PYTHONPATH=.:tests python -m unittest -v test_docker_updates.SocketBoundaryTests

No gate PostgreSQL existente, com serviço descartável PostgreSQL 17 e ESCRITURA_POSTGRES_TEST_DSN explicitamente definido pelo workflow:

    python tests/test_postgres_backend.py
    python tests/test_postgres_migration_stage.py

As entradas PostgreSQL dedicadas falham sem driver/DSN. Um skip local não é aprovação. Não remover testes, simular socket/servidor ou mudar permissões para encobrir impedimentos.

## CI e base desta publicação

Composição sobre develop b82a5dc7273ddfcb19484bb2d4049fd186f178eb, após PR55. Workflow ci.yml blob eff1c5cc5cd5e4a40f77787923091a9cefe9ce51: gates Linux e PostgreSQL preservados; jobs Windows/macOS condicionados a desktop_enabled. A política versionada desativa desktop para PRs com base develop. Nenhum workflow/política é alterado nesta PR.

A publicação antes aguardava esse fluxo; a condição foi atendida. PostgreSQL real e os três sockets ainda precisam ficar verdes no CI do SHA exato antes de qualquer merge. CI de outra PR não valida este patch.

## Medições sintéticas anteriores e limites

Produto medido na base 4204eae241b0b1ddccf71532708c33de9505e1f1: somente filtro e índice deste patch, diff SHA-256 a136f8da65cebe4d51574a27954543cfa65cd9966127dc121d62aacb53b56f0f. Em cópias do mesmo banco de 13.000 notas, confirmar 200 adicionais consumiu 57,843 s antes e 1,781 s depois; a consulta antiga consumia 55,721 s (96,33% do lote). A confirmação dos mesmos 13.000 XMLs caiu de 1.900,546 para 70,873 s, com originais/saídas iguais e totais/vínculos conferidos.

Uma nova carga completa de 90.030 XMLs individuais/180.060 itens terminou todas as etapas disponíveis em 1.475,771 s no overlay, sem retomar a tentativa de 38 mil que esgotou o tmpfs /tmp. Distribuição: 30 dias de 3.001 notas, três séries, 97 SKUs, dois itens por nota; total 27.279.090 centavos. RSS máximo global 871.636.992 bytes incluindo cliente/JSON; banco 3.269.541.888 bytes, com originais mantidos. Não houve baseline anterior de 90 mil nas mesmas condições. Não é SLA nem desempenho do servidor do usuário, nem economia de banco.

Os instrumentos e artefatos grandes continuam locais e não fazem parte deste pacote mínimo; estes números são resultados históricos, não uma nova execução nesta base nem uma receita completa de benchmark publicada. Não devem ser extrapolados para outro hardware, volume ou PostgreSQL. A migração do índice também tem custo: em cópia sintética de 13 mil, 0,024 s; isso não prevê tempo de migração de uma base real.

RECORD_LIMIT de 100.000 registros por arquivo permanece: um arquivo com 90.030 pares C100/C190 excede a proteção. SPED_FIELD_COUNT na reimportação do consolidado nativo também permanece; nenhum campo é truncado e nenhum erro é silenciado. Geração parcial e consolidação nativa opcional não são EFD oficial validada/PVA. XML e geração sobre escrituração ainda não têm todas as opções independentes de consolidação solicitadas; relatórios agrupados não são contabilização real.

A suíte integral histórica percorreu 1.190 testes: 1.154 passes, 33 saltos e três erros AF_UNIX do ambiente; não se declara verde. A rodada local desta publicação passou as 88 regressões acima em 37,264 s, sem falhas, erros ou saltos, no código final composto sobre dev.24. PostgreSQL real segue indisponível localmente por ausência de servidor/DSN; sockets ficaram impedidos pelo mesmo perfil AF_UNIX. Exigir provas reais em CI sem contornar esses limites.
