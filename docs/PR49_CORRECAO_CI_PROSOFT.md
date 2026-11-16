# PR49 — corrida de navegação no roteiro Chromium Prosoft

A falha do [CI 43815102624](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43815102624), head `6d074ad19d9db6354606ddce55ba3efabe9f186d`, foi confirmada nos logs do job Linux `133125255095` e no [artefato sintético 14202577340](https://github.com/codisplanfiscalai/escritura-integrada/actions/runs/43815102624/artifacts/14202577340). A base continua develop `67a5e2e0b3c65fe7948827d6d66da5361970bfb1`, dev.23. PR50 está aberta em outra frente e não foi modificada.

## Causa comprovada

O roteiro passou seus oito primeiros grupos Prosoft e depois executou `select_option(empresa B)` seguido imediatamente de navegação para Exportação Prosoft fiscal. A troca de empresa é assíncrona. Enquanto `state.contextBusy` está ativo, `App.navigate` retorna e preserva o contexto em curso; portanto aquele clique podia ser ignorado. Ao terminar a troca, a empresa B aparecia na tela Prosoft **contábil**. O campo genérico de código da empresa ficava habilitado nessa tela e não comprovava que a navegação fiscal havia ocorrido.

O próximo `fill` procurava **Espécie Prosoft do modelo 55**, campo existente somente na tela fiscal. O timeout de 15 segundos é consequência da tela errada. O texto visível do artefato confirma “Empresa sintética Prosoft B” e “Exportação Prosoft contábil”, sem o campo fiscal. Os logs indicam zero erros JavaScript; os 1214 testes do gate Linux haviam passado antes do roteiro. Uma exceção de renderer sintético presente em teste de falha do Auditor não é a causa desse job.

A causa foi reproduzida em bancos descartáveis com a fonte anterior e **750 ms de latência de rede via CDP**, tanto no Chromium 141 quanto no **Chromium 151.0.7922.34 com Playwright 1.62.0 iguais ao CI**. Nos dois casos houve o mesmo timeout no campo fiscal e a tela permaneceu contábil. A instrumentação de latência foi a única mudança da reprodução anterior à correção.

## Correção pontual e regressão permanente

Somente `scripts/browser_prosoft_export.py` muda entre os arquivos executáveis:

- O helper de navegação aguarda o seletor de empresa ficar habilitado, sinal observado de que a troca de contexto terminou.
- Depois do clique, exige a classe de guia selecionada no controle de destino.
- No cenário final, exige a empresa B e o título fiscal antes de editar os campos.
- Os 750 ms de latência permanecem no cenário, tornando obrigatória a cobertura da condição que provocava a corrida.

Nenhum código da aplicação, interface, serviço de domínio, permissão ou workflow foi alterado. O timeout continua em **15000 ms**, sem nova espera fixa para esconder a corrida, sem force click ou repetição silenciosa. Os nove grupos e todas as conferências anteriores de valores, layouts, downloads, repetição, hashes econômicos, competência fechada e contexto permanecem. Um décimo grupo comprova a navegação sob latência.

## Validação efetiva

- **Antes:** reprodução determinística falha em Chromium 141 e 151, no mesmo campo do CI, com a mesma latência de 750 ms.
- **Depois:** cenário completo passa no Chromium 141 e **três vezes consecutivas no Chromium 151**, dez grupos por execução e zero erros JavaScript, sempre sob 750 ms de latência no trecho problemático.
- **Integração de entradas/saídas no Chromium 151: sete grupos OK**, zero erros JavaScript. Preservados os dois acessos, entradas individuais, saídas individuais/diárias, prévia somente leitura, origens, competência fechada/reaberta, balanço/FK e repetição após perda de resposta sem duplicação.
- **124 testes backend em 11 módulos: OK**, sem falhas/erros/skips, 68,200 s incluindo carregamento; integrações fiscal/contábil, Prosoft, mapeamentos, composição, contexto e bootstrap. **181 testes frontend: OK**, 3,103 s.
- **Build Vite dev.23: OK**, 4,30 s; bundle 839,78 kB, gzip 249,28 kB, com o aviso de tamanho já existente. Sintaxe Python, paridade de versões e `git diff --check`: OK. Sem lint separado configurado.

[Resultados, reprodução e hashes](evidence/pr49-prosoft-ci-fix.json). A instalação de teste do navegador usa o arquivo oficial Chrome for Testing; o CDN do Playwright retornou ZIP inválido e essa tentativa não foi contada como validação. Dependências do produto não foram alteradas. As provas usam aplicação local, SQLite e temporários sintéticos isolados na worktree. Os artefatos do CI consultados também pertencem exclusivamente a esse roteiro sintético; nenhum backup, XML real ou log de instalação de usuário foi aberto.

Esta correção não repete localmente a suíte integral, instaladores/imagens, PostgreSQL operacional ou homologação em Prosoft/PVA; o novo CI deve ser conferido no head publicado. A integração segue parcial: importação automática, distribuição por itens e ligação dos botões individuais anteriores continuam pendentes. Sem merge final, release, implantação, produção ou alteração de branches paralelas. O trabalho local anterior foi preservado em sua worktree.
