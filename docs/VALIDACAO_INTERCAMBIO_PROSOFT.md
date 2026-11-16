# Validação independente do intercâmbio Prosoft

Ensaio original local sintético de 16/11/2026 sobre develop `67a5e2e0b3c65fe7948827d6d66da5361970bfb1`
(dev.23), após os merges PR40 e PR44. Branch de trabalho
`test/prosoft-independent-contract-20261116`. A única correção de produto é a validação pontual das espécies descrita abaixo.
Interface, schema, workflow, Atlas, release estável e produção não foram alterados.
A publicação deste incremento é uma PR em rascunho, sem merge ou implantação.
Outras frentes de integração contábil, prévia XML, conciliação e desempenho não
foram incorporadas ou alteradas.

## Método e fontes

As fontes são os layouts originais recebidos, lidos em diretório privado fora do
checkout: `layoutimportdos_29102026.pdf` (121 páginas) e `LAYOUT_CTBLCTOS.PDF`
(6 folhas). Não foram usados exemplos operacionais para criar fixtures ou
expectativas. Documentos de origem, pacotes e dados de clientes não acompanham
este incremento. Não houve conexão a Windows/RDP ou à base Prosoft.

`tests/prosoft_reference_reader.py` é um leitor exclusivo de testes, escrito a
partir das tabelas abaixo. Não importa módulos, constantes, formatos monetários
ou helpers de posição dos exportadores. Os testes consomem as rotas reais de
prévia/confirmação/download e comparam o conteúdo baixado com manifesto salvo,
hashes SHA-256, prévia e movimentos sintéticos. Helpers antigos só fornecem
setup e operações de cadastro; os testes anteriores não são herdados/executados
implicitamente como novos testes.

A conferência dos PDFs incluiu leitura das tabelas e inspeção visual renderizada
das folhas contábeis 4/5 e páginas fiscais 3/13, especialmente regras dos modos,
sequência dos LC2, cancelamento e identidade moderna. O leitor não é um
validador oficial, um importador do produto ou uma implementação completa do
layout. As posições abaixo são base 1; CRLF não entra no comprimento do registro.

| Referência original | Campos usados no leitor independente |
|---|---|
| Fiscal, entrada p.1 | Escrituração 19×6; emissão 25×6; desdobramento 43×1; conta 44×5; base 66×14; ICMS 80×14; outras 108×14; IPI creditado 155×14; valor contábil 211×14 |
| Fiscal, entrada pp.2/3 | CFOP 624×4; cancelada 809×1; espécie Windows 858×5; série 864×3; número moderno 869×10; chave 973×44 |
| Fiscal, entrada p.7 | Último campo 2335×6, resultando em 2340 posições |
| Fiscal, saída pp.11/12 | Desdobramento 19×1; escrituração 20×6; conta 26×5; valor contábil 34×14; base 62×14; ICMS 76×14; outras 104×14; IPI 132×14; emissão 728×6; CFOP 734×4 |
| Fiscal, saída pp.13/14 | Cancelada 930×1; espécie Windows 978×5; série 984×3; número inicial 989×10 e final 999×10; chave 1377×44 |
| Fiscal, saída p.17 | Último campo 2606×6, resultando em 2611 posições; p.18 inicia observações de preenchimento |
| Contábil, folha 1 | ASCII imprimível; valores R$ com 16 posições, 13 inteiros, ponto e dois decimais; formatos X/N/NZ e datas DDMMAAAA |
| Contábil, CTA folha 2 | Ordem 4×5; filler 9×3; acesso 12×5; classificador 17×15; nome 32×30; terceiro 62×1; centro 63×1; filler final 165×44; total 208 posições; precede LC1/LC2 |
| Contábil, LC1 folhas 4/5 | Ordem 4×5; filler 9×3; modo 12×1; data 13×8; documento 21×10; lote 31×5; origem 36×30; quantidade 66×3; contas/terceiros/centros 69..116; valor 117×16; histórico 133×240; filler 375×74; total 448 posições |
| Contábil, LC2 folha 5 | Ordem do LC1 em 4×5; sequência 9×3; natureza 12×1; acesso 13×5; terceiro 18×14; centro 32×5; valor 37×16; histórico 53×240; filler 294×49; total 342 posições; imediatamente após LC1 modo 2, até 200 partidas |

O perfil fiscal do aplicativo restringe DDMMAA a 2000..2099; o leitor aplica esse
intervalo explicitamente, sem o pivô de século de `%y`. Campo fiscal monetário
lido tem 11 inteiros, ponto e dois decimais. Branco significa ausente no leitor,
sem converter falta de informação em zero. CRLF é verificado como contrato de
arquivo do aplicativo; isso não comprova que seja a única terminação aceita pelo
importador. ZIP e JSON são invólucro e trilha do aplicativo, não registros Prosoft.

## Matriz de provas deste incremento

| Arquivo/registro ou comportamento | Prova nova | Limite da conclusão |
|---|---|---|
| ENTRADAS.TXT 2340 / SAIDAS.TXT 2611 | Leitura de posições sem constantes do encoder; datas distintas, número de 10 dígitos, chave e CFOP; hashes, tamanhos e amostras iguais à prévia | Somente cabeçalho parcial 55/65; não valida todos os campos reservados ou tributos |
| Centavos e totalizações fiscais | Vetores 0; 0,01; 0,09; 0,10; 0,99; 1,00; 100,01; 99.999.999.999,99; desdobramento 33,33 + 66,68; soma por nota, arquivo, direção e manifesto | Não representa decisão tributária nem crédito presumido |
| Tributos ausentes/informados | Leitura distingue None de zero; reconcilia bases/ICMS/outras/IPI presentes com total e contagem do manifesto nos cenários | Não comprova adequação tributária nem interpretação de brancos pelo destino |
| Espécies NF-E/NFC-E | Correção exata em configuração e encoder, com prévia/download e controles negativos de formato/comprimento | Cinco posições conferidas no PDF; grafias adicionais solicitadas não comprovam cadastro/aceite no destino |
| Canceladas | Nota escriturada com evidência de livro, identificador preservado, indicador de saída 930=1, total zero e contagem; controles negativos de flag | Entrada 809=1 e demais guardas continuam na suíte anterior; não infere evento eletrônico ou Situação Docto |
| Empresa/competência/seleção fiscal | Competência novembro aceita emissão outubro; documento dezembro e de outra empresa rejeitados na seleção; saída isolada preserva motivo de entrada não escolhida | Não ensaia outra instalação Prosoft ou concorrência real |
| CTBLCTOS / LC1 simples e LC1+LC2 detalhado | Decodificação, sequência/vínculo LC1/LC2, quantidade, filler, natureza, conta e valores; total débito=crédito=manifesto; rastreio ao lançamento original | Histórico/terceiro/centro são lidos, mas esta nova amostra só usa terceiro vazio e centro zero; variantes continuam nos testes existentes |
| CTA opcional | Mesmos lançamentos com CTA desligado/ligado; cadastro antes do LC1; código/classificador/filler; trilha de lançamentos invariável | Não consulta existência de conta no destino nem implementa cadastro completo de terceiros |
| Referência curta | Vetor sintético conhecido `SYNTHETIC REFERENCE 2026-11` → `YZF5USNWLD`; original/hash no manifesto; igualdade no TXT, seleção parcial e replay; original da aplicação preservado | Algoritmo é contrato aprovado do aplicativo, não regra do PDF; colisões reais/forçadas continuam cobertas na suíte anterior |
| Manifesto contábil salvo | JSON baixado igual ao manifesto da prévia e confirmação; SHA-256 do TXT e amostras; journal_id/ordem/partidas/valores reconciliados | Manifesto contábil não contém empresa/competência próprias: escopo vem da rota, filename e lote; não é documento importável no Prosoft |
| Empresa/competência/seleção contábil | Lançamento de outra empresa/mês rejeitado; seleção parcial contém apenas o lançamento pedido | Não comprova permissões da instalação de destino |
| Síntese visual diária versus lançamento real | Relatório agrega dois lançamentos em duas linhas visuais, mas TXT conserva dois LC1; geração diária real posterior produz um LC1 e rastreia suas duas notas pelo serviço existente | Não altera geração contábil e não valida as novas funcionalidades da PR49 |
| Integridade local | Hashes econômicos antes/depois iguais, replay do lote contábil e mapa estável; nenhuma escrita nos movimentos por exportação | Idempotência local não impede duplicação ao reimportar no destino |
| Sensibilidade do leitor | Rejeita CRLF quebrado/registro vazio, largura incorreta, ASCII inválido, decimal com vírgula, desequilíbrio, detalhe faltante, ordem/pai/partida errados, filler alterado e LC2 fora do lugar | Controles negativos pontuais; não é fuzzing ou prova de validação completa de toda corrupção possível |

Testes novos em `tests/test_prosoft_reference_contract.py`: nove casos, incluindo
vetores e controles negativos por subcaso. A suíte anterior já cobre guardas,
colisões forçadas, repetição de referência, cancelamento de entrada, mapeamentos
versionados, permissões e contexto; não se atribui essa cobertura aos nove novos
casos. A correção pontual de espécies foi incorporada após a reprodução descrita abaixo.

## Correção pontual: espécies NF-E/NFC-E

O código atual de develop foi conferido, não apenas o checkout histórico citado
no relato. A mesma restrição estava no encoder (`app/prosoft_fiscal.py`) e no
salvamento dos mapeamentos (`app/prosoft_settings.py`): só letras maiúsculas e
números, até cinco caracteres. Com fixtures novas, os dois códigos solicitados
foram rejeitados antes do patch: quatro combinações modelo/direção foram omitidas
com `species_mapping_required`, e a configuração retornou HTTP 400.

As páginas 3/13 do PDF confirmam campos Windows de cinco posições, mas **não
listam NF-E/NFC-E como códigos cadastrados**. A tabela da entrada descreve o
campo como alfanumérico; a de saída admite espécie de nota ou uma exceção de
transporte. Portanto, o PDF sozinho não é prova do hífen ou da existência dessas
espécies na instalação. As grafias NF-E e NFC-E vêm da orientação específica de
compatibilidade recebida nesta tarefa e cabem, sem corte, nos campos conferidos.
Não se atribui ao PDF uma tabela de códigos que ele não contém.

O patch é uma função pequena em `app/prosoft_profiles.py`, compartilhada pelas
duas validações. Aceita os códigos alfanuméricos anteriores e **somente as duas
grafias adicionais exatas** NF-E e NFC-E. Não permite hífen arbitrário nem novas
pontuações; não remove espaços, troca caixa ou trunca valores. Código vazio
continua permitido apenas na configuração não confirmada; exportar exige código
válido e confirmação como antes. A interface já comporta cinco caracteres e
não foi alterada. Nenhum código foi preenchido automaticamente.

Os testes novos verificam ambas as direções/modelos no encoder, bytes dos campos
858×5/978×5 (incluindo o espaço de preenchimento de NF-E), salvar/recarregar
mapeamentos, prévia, confirmação e download com leitura independente. Espaço
inicial/final/interno, seis caracteres, hífen fora dessas grafias, pontuação,
minúsculas, Unicode e controle continuam rejeitados. A configuração inválida não
substitui a versão salva. A confirmação do operador é uma declaração de
mapeamento, sem consulta ao cadastro remoto; `homologated_in_destination` continua
false. O contábil não ganha campos ou regras novos.

## Execuções locais e reprodução

Antes do patch de espécies, a execução conjunta passou: **151 testes em
76,921 s**. Depois do patch, os **nove casos novos passaram em 2,436 s**, sem
falhas, erros ou skips. A execução conjunta final passou: **154 testes em 73,573 s**, sem falhas,
erros ou skips. Inclui os nove novos casos, `test_prosoft_increment`,
`test_prosoft_cancel_references`, `test_prosoft_settings`,
`test_prosoft_reception_composition`, `test_fiscal_sales_accounting`,
`test_business`, `test_journal_participants` e `test_core`. Dados e bancos são
sintéticos e temporários. O log completo está fora do checkout; a evidência
reprodutível são os testes e o comando abaixo.

```sh
PYTHONPATH=tests:. python -m unittest test_prosoft_reference_contract test_prosoft_increment test_prosoft_cancel_references test_prosoft_settings test_prosoft_reception_composition test_fiscal_sales_accounting test_business test_journal_participants test_core -v
```

No executor, dependências opcionais preexistentes de testes foram resolvidas
nos diretórios temporários isolados já disponíveis, adicionados ao PYTHONPATH;
requirements e locks do projeto não foram alterados. Não foram executados nesta
frente suite integral, navegador, frontend/build de produto, binários, imagens,
PostgreSQL real, importação Prosoft ou PVA. Não há mudança de interface, dependências ou locks. O patch é de validação
Python. A execução não estabelece desempenho ou concorrência reais. O resultado
do CI remoto deve ser conferido na PR para o head exato; os testes locais não
substituem essa verificação.

## Composição atual da PR51 com develop dev.26

A base atual é `12103b555d295489fe6a06de836c00b257562ce2`, com os manifests
0.9.0-dev.26. Inclui a política de CI da PR55, seleção de bind Docker da PR54 e
indexação da busca de cancelamentos NFC-e da PR57. O primeiro pai público é o
head anterior da PR51 `b049997795fdff5c0ddfd3d593973974ea8d0e1a`; o segundo é a
base dev.26. A sincronização foi preparada sem conflitos, rebase ou force push.

Os três arquivos de produto e os dois arquivos de testes próprios da PR51
permanecem byte a byte iguais ao head anterior. Todos os workflows, scripts,
templates Docker, core, banco e contratos/fixtures de identidade NFC-e foram
conferidos como idênticos à base. A PR não modifica essas frentes. A política
existente mantém desktop pausado para develop, passa a branch-base ao
planejamento e condiciona Windows/macOS a `desktop_enabled`; os gates de main e
cenários Chromium existentes permanecem preservados.

A revalidação inclui os módulos Prosoft/core/contabilização e contratos CI
anteriores, mais `test_deploy_storage`, `test_book_cancellation`,
`test_nfce_identity_lookup` e `test_nfce_identity_contract`. Sintaxe dos 295
arquivos Python, YAML e manifests de versão também passaram. A suíte desta
composição passou em **314 testes em 80,974 s**, sem falhas, erros ou skips.
O CI do head exato está na descrição da PR; CI de um pai anterior não
aprova a composição atual. Não houve merge desta PR em develop, build/publicação
manual de imagens, implantação ou acesso à instalação Prosoft.

## O que ainda não está comprovado

Nenhum arquivo foi importado na instalação Prosoft. O resultado é compatibilidade
estrutural e reconciliação interna nos casos executados, não homologação.

TRC e SLD continuam não implementados. Permanecem pendentes os demais 18 modelos
fiscais inventariados, itens/faturas/cadastros/meios de pagamentos e os três
modelos Excel; campos fiscais não cobertos seguem com os limites existentes.
ST/FCP/DIFAL, PIS/COFINS, IBS/CBS e ajustes não ganham cobertura por este leitor.
A [matriz geral](MATRIZ_LAYOUTS_PROSOFT.md) inventaria os registros e modelos;
seu texto histórico de publicação não substitui o estado atual dos merges.
SPED é ferramenta interna separada e não substitui os layouts próprios Prosoft.

## Requisitos exatos para um futuro ensaio de importação

1. Identificar versão/build do Prosoft e rotinas fiscal/contábil, versão de layout
   aceita e configurações de importação. Disponibilizar uma instalação de ensaio
   isolada, sem conexão/escrita na base real; autorização e credenciais próprias
   para esse ambiente, quando o ensaio for solicitado. Este trabalho não pede nem
   usa credenciais de produção.
2. Criar empresas e competências exclusivamente sintéticas no destino; confirmar
   empresa de quatro dígitos, plano 050 ou plano explicitamente escolhido, contas,
   espécies 55/65, terceiros/centros quando aplicáveis e tabelas da instalação.
   Empresa/plano fiscais não estão nos TXT; plano contábil também não é campo
   CTBLCTOS. As escolhas precisam corresponder à configuração no destino.
3. Registrar estado inicial verificável e mecanismo de restauração da base de
   ensaio. Gerar e guardar o par exato de TXT/manifesto/hash, configuração e
   prévia. Extrair os TXT do ZIP para a rotina apropriada; não presumir que o
   importador leia ZIP/JSON.
4. Importar inicialmente amostras pequenas, separadas por layout/modo: nota
   regular, nota desdobrada, cancelada validada com valor zero, LC1 simples,
   LC1+LC2 detalhado, referência longa abreviada e CTA opcional somente para conta
   movimentada ausente no destino. Repetições exigem restauração da amostra ou
   comprovação da política do destino, pois a idempotência local não basta.
5. Guardar log de aceite/rejeição, parâmetros e relatórios pós-importação da base
   de ensaio. Conferir quantidades, emissão versus escrituração, empresa/plano,
   conta/CFOP, espécie/número/chave, indicador de cancelamento, branco versus
   zero, débitos/créditos, histórico, referência/mapa e origens. Reconciliar com
   os hashes e totais do manifesto antes de qualquer declaração de aceite.
6. Documentar individualmente diferenças e registros/campos aprovados. Regra
   desconhecida, ambiguidade ou rejeição requer evidência específica; não
   preencher lacunas por suposição ou declarar suporte completo por um único
   lote aceito. Não transmitir, encerrar competência ou alterar produção.
