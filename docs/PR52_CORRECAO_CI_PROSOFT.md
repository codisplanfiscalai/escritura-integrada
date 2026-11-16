# Correção pontual do roteiro Prosoft na PR52

O CI 43865382498 do head 70d1285d9db5da21295fd09c107684041487026a falhou no passo Prosoft do job Linux 133292476518, esperando o campo fiscal Espécie Prosoft do modelo 55. Base: develop dev.29, 4e031a1b34ea695d8768af4d30224197d9178ea3.

## Causa e reutilização

Antes de modificar, a consulta de PRs identificou a correção equivalente na PR49, commit d39963a66de08ca0ec5c0b03928bc2771f71eb81. O roteiro anterior da PR52 tem o mesmo blob 5ece208e3c48c34bdb962b020ed4bcfea42cc53d do pai dessa correção. Foi reaproveitado exclusivamente scripts/browser_prosoft_export.py, sem incorporar funcionalidades ou outros arquivos da PR49.

A troca para empresa B é assíncrona. App.navigate retorna enquanto contextBusy está ativo. O roteiro clicava imediatamente na navegação fiscal; o clique podia ser ignorado. O campo genérico de código da empresa ficava habilitado na tela contábil e não demonstrava que a guia fiscal estava ativa. A captura sintética local confirmou empresa B, módulo Contábil e título Exportação Prosoft contábil.

A reprodução executou o roteiro anterior inteiro, adicionando em memória somente 750 ms de latência via CDP no trecho problemático e separando o diretório de artefatos. No Chromium 141.0.7390.37 falhou após oito grupos, exatamente no fill do campo fiscal com timeout de 15000 ms e zero erros JS. Não foram usados dados reais.

## Correção e prova

O helper aguarda o seletor de empresa habilitado antes do clique e exige a guia selecionada depois. O cenário também exige empresa B e título fiscal antes de editar os campos. A latência de 750 ms permanece como regressão permanente. O timeout continua 15000 ms; não há retry, force click, aumento de timeout, remoção de assertions ou espera fixa acrescentada para esconder a corrida. A proteção de contexto do produto permanece intacta.

O fluxo corrigido inteiro passou no mesmo Chromium 141 com dez grupos e zero erros JS: downloads e posições de arquivos, canceladas, referência curta e mapa, valores, hashes econômicos, competência fechada, mobile, respostas antigas e contexto. Backup: 42 executados, 41 passaram e um skip Windows nativo. Prosoft backend: 64 passaram. Frontend: 183 passaram. Build Vite, sintaxe Python e diff-check passaram; aviso de bundle grande permanece.

Reprodução e evidência atual: docs/evidence/pr52-prosoft-context-fix.json. Artefatos locais em artifacts/browser-prosoft-export-baseline, artifacts/browser-prosoft-export e artifacts/prosoft-fix. Os arquivos baixados são exclusivamente sintéticos e não são publicados.

O gate agregado não foi repetido para esta alteração somente de roteiro/documentação. No código funcional idêntico do head anterior, o gate local executou 1335 testes com zero falhas de asserção, três erros EPERM de sockets e 40 skips: não aprovado. Nenhuma restrição foi contornada. O CI remoto deve validar o novo head; resultado anterior não é aprovação dele. Chromium do CI, Windows nativo, contas cloud e homologação Prosoft não foram executados localmente nesta rodada. PR58, workflows, produto, dependências, develop e produção permanecem intocados. Sem merge ou implantação.
