# Exportação nativa TRC PJ mínimo

Base de implementação: develop `4610314bc94abbbcecaf271c0e87ca04623525d3`
(dev.39). Este incremento acrescenta cadastro de terceiros PJ no próprio TXT
CTBLCTOS, junto de LC1/LC2 e CTA opcional. Não gera SLD, não usa a consulta de
saldos observados como abertura oficial e não substitui formatos Prosoft por
SPED. Não consulta nem escreve na instalação Prosoft.

## Contrato efetivamente coberto

Referência: `LAYOUT_CTBLCTOS.PDF` fornecido, folha 1 (ASCII e formatos), folha 3
(tabela TRC) e folha 4 (obrigatoriedade, terceiros movimentados/ausentes e ordem
antes dos lançamentos). A folha 3 foi conferida também por renderização visual.
Os documentos originais não são dependências de teste nem acompanham o Git.

Perfil do aplicativo `TRC-PJ-646-minimal-v1` (não identifica a versão da instalação Prosoft): registro de **646 posições**, ASCII imprimível e
CRLF fora do comprimento. Somente pessoa jurídica, com CNPJ numérico completo
(14 dígitos, validado pelo normalizador existente), mapeado como terceiro normal.
O perfil mínimo cobre os campos obrigatórios assinalados pelo documento:

| Campo | Posição base 1 | Preenchimento |
|---|---|---|
| Tipo | 1×3 | TRC |
| Ordem | 4×5 | Sequencial próprio, de 00001, sem compartilhar contador de CTA/LC1 |
| Filler | 9×2 | Brancos |
| Tipo de terceiro | 11×1 | 0, pessoa jurídica |
| CNPJ | 12×14 | Código de destino explícito, sem pontuação, corte ou troca de identidade |
| Razão social | 26×60 | Informada no mapeamento, à esquerda com brancos; conversão ASCII exige revisão |
| Apelido | 86×20 | Informado, à esquerda com brancos; sem nome/apelido inventado |
| UF | 275×2 | Duas letras maiúsculas explicitamente informadas |
| Restante | 106..274 e 277..646 | Brancos: campos opcionais e filler não preenchidos por este perfil |

A divergência CPF entre convenção geral e tabela TRC e a sobreposição dos campos
pessoais 501..508 continuam pendentes. CNPJ já ocupa as 14 posições, sem depender
da interpretação divergente de alinhamento de CPF. Campos pessoais ficam em
branco; não se resolve a ambiguidade por suposição. Não são emitidos registros de
pessoa física, identidade livre, CPF ou CNPJ alfanumérico. Endereço completo,
telefones, registros, datas, municípios/país e indicadores opcionais permanecem
em branco, sem inferir zeros, N/S ou códigos da instalação. A aceitação de
cadastro mínimo e a interpretação de brancos precisam de ensaio no destino.

## Operação e compatibilidade

Na subguia de configuração já existente de Integração Prosoft contábil:

1. Escolher LC1/LC2 + TRC ou LC1/LC2 + CTA + TRC no tipo de exportação.
2. Manter o código da conta e sua política de referência a terceiro escolhidos.
   A partida deve ter terceiro e a política da conta deve ser opcional/obrigatória.
3. Nos terceiros das partidas, informar o CNPJ como código normal e conferi-lo;
   selecionar cadastro TRC PJ, declarar ausência no destino e informar razão
   social, apelido e UF. Nenhum cadastro remoto é verificado automaticamente.
4. Salvar por empresa quando desejar reutilizar a configuração. Gerar a prévia,
   revisar registros, origens e eventuais conversões ASCII e confirmar pelo fluxo
   existente. O TXT mantém `CTBLCTOS<empresa4>_<AAAAMM>.TXT`.
5. Após criar o terceiro no destino, desmarcar sua inclusão TRC e salvar, evitando
   reaplicar cadastro indevidamente. A idempotência do aplicativo não impede
   duplicação ou alterações ao reimportar no Prosoft.

Também é possível usar as rotas de settings/preview/confirm já existentes. Cada
mapeamento de `participants` pode ter `create_third` com apenas:
`destination_missing: true`, `person_type: legal`, `name`, `alias`, `state`.
Não são lidos dados extras do catálogo de terceiros para completar o registro.
O cadastro do aplicativo e os lançamentos originais permanecem inalterados.

TRC é opt-in explícito em `record_types`. API legada sem essa seleção continua
usando LC1/LC2/CTA; defaults de configurações novas continuam LC1/LC2. Sem TRC,
bytes, manifesto e identidade histórica dos payloads antigos permanecem
compatíveis. Desligar a opção mantém os dados preparados no mapeamento. A
confirmação continua sujeita à versão de settings, prévia/hash e permissões
existentes, sem rotas ou permissões paralelas.

Somente terceiros efetivamente referenciados nos lançamentos selecionados da
empresa/competência são considerados. Mapeamentos não usados não geram TRC.
Terceiro fixo de conta sem ID de participante não cria cadastro por inferência.
Duas identidades locais com o mesmo CNPJ e definição exportada idêntica recebem
um TRC; definições divergentes são rejeitadas antes de gravar lote/auditoria.
Ordens são determinísticas por CNPJ. CTA/TRC precedem os LC1; LC2 segue seu LC1.

O manifesto acrescenta, apenas quando TRC é selecionado:
`third_registration_profile`, `third_registrations` (ID local, CNPJ de destino,
ordem, IDs dos lançamentos e SHA-256 do registro sem CRLF) e contagem TRC.
O SHA-256 do arquivo e os totais de débitos/créditos continuam no contrato atual.
O download do manifesto reaproveita a rota protegida existente. Seleção explícita
TRC com zero cadastros tem identidade própria, preservando seu manifesto, mesmo
quando os bytes LC1/LC2 coincidem com os de outro perfil. Não se afirma cadastro
no destino nem homologação: `homologated_in_destination` permanece false.

## Provas sintéticas e limites

`tests/test_prosoft_trc.py` cobre posições/tamanhos/ASCII, campos em branco,
referências LC1/LC2, CTA + TRC, ordem/deduplicação, definição conflitante,
rejeição PF/livre/CPF/alpha CNPJ e dados fora do formato, conversão ASCII,
originais preservados, empresas/competências/seleção, configuração versionada,
permissões/CSRF, competência fechada, prévia/manifesto/download e replay.
As expectativas de posições são literais da folha 3 e não importam constantes
do encoder. Controles de conflito comprovam ausência de lote/auditoria parcial.

Os testes frontend cobrem as quatro escolhas contábeis e rascunho/mapeamento TRC
por empresa, alteração que invalida arquivo antigo e desligamento sem apagar
configuração. O roteiro Chromium existente foi ampliado com fluxo TRC persistido,
TXT/manifesto reais sintéticos e conferência de campos/hash, conservando os
cenários anteriores de contexto, competência, teclado, desktop/mobile e latência.

Validação final local: **191 testes backend passaram em 84,547 s**, sem falhas,
erros ou skips, incluindo os 15 novos testes TRC e regressões fiscais/contábeis,
saldos observados, terceiros, contexto e contabilização existente. **204 testes
frontend passaram** e o build Vite passou (aviso preexistente de chunk acima de
500 kB). Chromium 141.0.7390.37 passou em **14 grupos**, sem erros JavaScript,
com downloads, persistência/reload, desktop 1440/mobile 390, latência/contexto e
hashes econômicos preservados. Capturas exclusivamente sintéticas foram
inspecionadas localmente. Sintaxe dos 338 arquivos Python e diff-check passaram.
Os logs, imagens e arquivos temporários não acompanham o Git. O CI do head
publicado é identificado na PR e precisa ser conferido separadamente. Não houve
importação Prosoft real, consulta de cadastro no destino, transmissão ou uso de
dados reais. Não foram executados localmente suíte integral, PostgreSQL real,
outros navegadores, instaladores/imagens ou ensaio de carga. CI e testes internos
não homologam a instalação Prosoft. Permanecem os requisitos de uma base de
ensaio isolada, versão/rotina confirmadas, empresa/plano/cadastros coerentes,
restauração e reconciliação pós-importação descritos na
[validação do intercâmbio](VALIDACAO_INTERCAMBIO_PROSOFT.md).
