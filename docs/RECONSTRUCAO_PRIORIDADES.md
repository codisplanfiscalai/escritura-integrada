# Reconstrução das correções prioritárias

Este incremento foi reconstruído a partir de `develop` (`d11ba3bbdf7ba5ee71261315255b8dcbe5003976`). Não é a recuperação binária dos commits locais anteriores. Os testes dessa reconstrução precisam corresponder ao SHA indicado nos relatórios produzidos em `artifacts/`.

## Escopo

- Contexto F8 com busca por código, F9 com limpeza consistente e rolagem discreta/acessível.
- Competência sugerida nas consultas e exportação contábil, preservando filtros manuais e sem alterar o período operacional.
- Séries numéricas com tamanho mínimo por empresa e correção de existentes somente após prévia e confirmação, preservando dados e recusando conflitos.
- Preparação assistida da apuração, prévia não persistente, base declarada inequívoca e proteção contra alterações concorrentes.
- Terceiro explícito nas partidas e importações v2, contabilização posterior de documentos escriturados e exportação contábil por participante.

As alterações de série incrementam a versão dos documentos e invalidam memórias de apuração afetadas. A contabilização posterior preserva a versão e os valores fiscais. Testes cruzados exercitam esses contratos e a preservação dos mapeamentos de terceiros ao trocar a competência de exportação.

## Validação e limites

O gate `python -m scripts.ci.checks` valida a sintaxe, os assets compilados e as suítes Python e frontend. Os cenários Chromium de contexto, apuração e séries têm etapas bloqueantes e artefatos próprios nos workflows de CI e release. Não executar um navegador local não equivale a aprovar visualmente a interface.

Os testes e cenários usam bases sintéticas isoladas. Não há migração retroativa de terceiros de lançamentos antigos, preenchimento automático de terceiros nas baixas financeiras ou homologação Prosoft. A migração aditiva das partidas exige backup prévio, inclusive para bancos que já declaram schema 6 mas ainda não possuem a coluna.

Este incremento não inclui a expansão anterior dos relatórios financeiros, o novo perfil de exportação fiscal Prosoft ou a preparação de serviços Docker. Publicação, implantação e execução sobre dados reais são etapas separadas.
