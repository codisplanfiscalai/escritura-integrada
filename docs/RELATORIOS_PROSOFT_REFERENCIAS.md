# Referências verificáveis para relatórios Prosoft

Data da inspeção: 09/11/2026. Escopo: inventário local e documentação, sem executar binários, alterar código, publicar ou homologar relatórios.

## 1. Força da evidência e conclusão

- **D (direta):** PDF/arquivo efetivamente aberto nesta revisão; renderização visual onde indicada.
- **S (secundária):** catálogo ou análise anterior presente no checkout. Confirma o que foi registrado, não uma nova leitura do binário original.
- **I (inferência/projeto):** contrato proposto para implementação; precisa de testes e validação contábil/fiscal.

Há modelos diretamente inspecionáveis de Razão Analítico Individual, Plano de Contas, Registro de Entradas P1/A, Registro de Saídas P2/A e Apuração do ICMS P9. Para os demais relatórios, o checkout fornece títulos de formulários e sínteses estáticas. A verificação complementar da seção 9 recuperou o pacote na Space e confirmou diretamente interfaces, controles e gabaritos estáticos, mas não encontrou PDFs/prints dentro dele. Não é possível certificar que todos os relatórios sejam idênticos à Prosoft com este conjunto.

Os livros fiscais históricos não exibem identificação de fabricante no texto extraído. Seus metadados de impressão não comprovam autoria Prosoft. Devem ser chamados de **modelos fiscais fornecidos**, até confirmação da origem. O mesmo cuidado vale para atribuir a um executável específico o PDF de Razão recebido.

## 2. Fontes e disponibilidade

Caminhos de fontes privadas abaixo são relativos à raiz de trabalho, não ao checkout. Os originais não são incorporados ao repositório e não se transcrevem dados pessoais ou valores de clientes neste documento.

| ID | Fonte | Evidência e limite |
|---|---|---|
| S1 | `docs/referencias/inventario-18-executaveis.csv` | 18 executáveis, versões, controles e falhas da recuperação histórica. |
| S2 | `docs/referencias/formularios-identificados.csv` | 281 entradas de formulário/controle, primeiro rótulo, caminho e linha. Não contém todos os captions ou posições dos controles. |
| S3 | `docs/referencias/verificacao-binarios.json` | Registro histórico de comparação de hashes de 18 binários; a busca complementar revalidou 18/18 dentro do ZIP, conforme seção 9. |
| S4 | `docs/MATRIZ_RASTREABILIDADE.md` e `docs/ANALISE_E_PROPOSTA.md` | Sínteses históricas, referências a formulários e prints. Não substituem imagem ou fonte original. |
| S5 | `docs/referencias/razao-comparacao-0_7.json` | Resultado histórico: 403 linhas, 7 páginas de referência e geradas, diferenças monetárias zero; tipografia/quebras diferentes. Não é novo teste nem equivalência pixel a pixel. |
| D1 | `prosoft_review_20261104/materials/Contabil/Prosoft.zip` | ZIP listado sem executar conteúdo: apenas 5 arquivos, descritos abaixo. Não contém os 18 EXEs. |
| D2 | `prosoft_review_20261104/materials/Contabil/DIX_092026_Pacote_Integracao_Prosoft/DIX_092026_Integracao_Prosoft/07_cadastros/fontes/RAZAO_CAIXA_082026_REENVIADO.PDF` | Texto de todas as páginas e render da página 1 examinados. |
| D3 | `prosoft_review_20261104/materials/Contabil/PLANOCONTAS0050.PDF` | Texto e render da página 1 examinados. |
| D4 | `incoming_books_20261030_1334/06.2022/06.2022/Livro Registro de Entradas.pdf` | Texto e render da página 1 examinados. |
| D5 | `incoming_books_20261030_1334/06.2022/06.2022/Livro Registro de Saídas.pdf` | Texto integral extraído; render da página 1 examinado. |
| D6 | `incoming_books_20261030_1334/06.2022/06.2022/Livro Registro de Apuração do ICMS.pdf` | Texto integral extraído; render da página 2 examinado. |

`Prosoft.zip` contém `LAYOUT_CTBLCTOS.PDF`, `layoutimportdos_29102026.pdf`, `ContasPagarReceberModeloPadrao.xlsx`, `InventarioModeloPadrao.xlsx` e `PlanoDeSaudeR4010ModeloPadrao.xlsx`. São contratos/modelos de importação, não um catálogo de saídas impressas. O contrato LC1/LC2 nas páginas 4–6 de LAYOUT_CTBLCTOS já é referenciado em S4; ele não define o layout do Razão nem prova seu algoritmo. As células dos três XLSX não foram auditadas nesta revisão.

O diretório `room_review` contém imagens e estudo dimensional de sala, não prints fiscais/contábeis. As imagens em `docs/images` são da aplicação nova, portanto não servem como prova do desenho legado. O MHTML e `conversa-extraida.txt` foram examinados de modo focal para localizar o nome do pacote de engenharia reversa; não forneceram um original local verificável. Na inspeção local inicial, não foram encontrados `.frm` ou `Projetos_Engenharia_Reversa.zip` nas áreas pesquisadas. A busca complementar na Space localizou e materializou o ZIP, conforme seção 9; essa lacuna local foi resolvida.

## 3. Modelos com PDF diretamente verificável

### 3.1 Razão Analítico Individual (D2)

- Título literal: `RAZÃO ANALÍTICO INDIVIDUAL`.
- Cabeçalho: Folha, Empresa (código e nome), CNPJ, Período inicial/final; linha de Conta com acesso, classificador e nome.
- Colunas, nesta ordem: **LCTO; DCTO; DATA; C/PART.; C/C; HISTÓRICO; DÉBITO; CRÉDITO; SALDO**. Sufixo de natureza D/C junto ao saldo.
- Corpo: saldo anterior pontilhado; datas em dia/mês; históricos que podem continuar em outra linha; valores em formato brasileiro com duas casas; saldo mostrado em fechamentos de grupos de data, não necessariamente em toda partida.
- Continuação: título/cabeçalho repetidos nas páginas; indicação `(C.)` junto à conta nas páginas seguintes. Última página termina em `SALDO FINAL` com totais de débito e crédito e saldo.
- Desenho: retrato, preto e branco, linhas horizontais no cabeçalho, sem grade vertical no corpo, texto de corpo monoespaçado, numéricos alinhados à direita. Página PDF: 794 × 1122 pontos. Sete páginas; número de folha impresso começa em 00002, diferente do índice físico do PDF.
- Limites: não há tela de parâmetros diretamente disponível; conta, período e folha são evidência do cabeçalho, não prova de cada opção de seleção. Não copiar dados do cliente para fixtures públicas.

### 3.2 Listagem do Plano de Contas (D3)

- Cabeçalho: `Contabilidade`, Data Emissão, Folha, `Plano de Contas` e código do plano.
- Colunas: **Acesso; Classificador; Nome da Conta; Lçto; Cor.; Red.; Custo; Tx.Moeda; Conc.; Contas DmBL; Seq; DIPJ**.
- Paisagem, texto monoespaçado, cabeçalho separado por linhas horizontais, sem grade vertical no corpo. Contas sintéticas em maiúsculas; analíticas e indicadores abaixo delas; classificador pontuado e acesso com dígito separados.
- Não deduzir significado integral dos indicadores nem natureza da conta apenas da sigla/classificador. A legenda e regras devem ser confirmadas antes de atribuir comportamento.

### 3.3 Registro de Entradas P1/A (D4)

- Título `REGISTRO DE ENTRADAS`, modelo P1/A, Folha; Contribuinte, CNPJ, Inscrição Estadual, Mês ou Período/Ano.
- Colunas hierárquicas: **Data de Entrada; Documentos Fiscais [Espécie, Série/SubSérie, Número, Data do Docto, CNPJ do Emitente/Nome do Emitente, UF Origem, Inscr. Estadual]; Valor Contábil; Codificação [Contábil, Fiscal]; Valores Fiscais [ICMS/IPI, Cód. (a), Base de Cálculo/Valor Operação, Alíquota %, Imposto Creditado]; Observações**.
- Legenda explícita: 1 = operações com crédito do imposto; 2 = sem crédito, isentas/não tributadas; 3 = sem crédito, outras.
- Paisagem, título centralizado com letras espaçadas e sublinhado, grade de cabeçalho em múltiplos níveis, linhas verticais no corpo, emitente em duas linhas, alíquota com quatro casas. Rodapé da primeira página `A Transportar` e totais alinhados à respectiva coluna.
- Implicação para implementação: código fiscal/código de valor fiscal e separação ICMS/IPI não podem ser inventados a partir de um único total genérico. Data de entrada e emissão são campos distintos. PDF não demonstra tela de filtros nem regras de composição de linhas.

### 3.4 Registro de Saídas P2/A (D5)

- Título `REGISTRO DE SAÍDAS`, modelo P2/A; cabeçalho de contribuinte/inscrição/CNPJ/período e folha como Entradas.
- Colunas: **Documentos Fiscais [Espécie, Série-SSer., N. Inicial/N. Final, Dia, UF Dest]; Valor Contábil; Codificação [Contábil, Fiscal]; Valores Fiscais [Operações c/Débito do Imposto: Base de Cálculo, Alíquota %, Imposto Debitado; Operações s/Débito do Imposto: Isentas ou Não Tributadas, Outras]; Observações**.
- Paisagem, agrupamentos de cabeçalho e grade vertical; coluna de observações ampla. Amostra contém NF-e e NFC-e; canceladas permanecem identificadas com `***CANCELADA***` e valores zerados. Rodapé `A Transportar`, com totais por coluna monetária. Alíquotas com quatro casas.
- Número inicial/final não autoriza comprimir intervalos arbitrários nem somar documentos cancelados. Cada regra de agrupamento precisa de confirmação/fixture.

### 3.5 Apuração do ICMS P9 (D6)

- Página 1: `REGISTRO DE APURAÇÃO DO ICMS`, modelo P9; contribuinte/IE/CNPJ/página/período. Seções ENTRADAS e SAÍDAS com **Codificação Contábil/Fiscal; Valores Contábeis; Base de Cálculo; Imposto Creditado ou Debitado; Isentas/N.Tributadas; Outras**. Subtotais por origem/destino (Estado, Outros Estados, Exterior) e total.
- Página 2: `RESUMO DA APURAÇÃO DO IMPOSTO`, retrato, quadro com **Coluna Auxiliar** e **Somas**, seções verticais Débito, Crédito e Saldo.
- Linhas numeradas: 001 saídas/prestações com débito; 002 outros débitos; 003 estorno de créditos; 004 subtotal; 005 entradas/aquisições com crédito; 006 outros créditos; 007 estorno de débitos; 008 subtotal; 009 saldo credor anterior; 010 total; 011 saldo devedor; 012 deduções; 013 imposto a recolher; 014 saldo credor a transportar.
- Ajustes são discriminados em linhas de texto, valores auxiliares e totais. Rodapé: Informações Complementares, Guias de Recolhimento [Número, Data, Valor, Órgão Arrecadador], Guia de Informação [Data da Entrega, Local da Entrega], Observações.
- Não confundir reprodução do quadro com cálculo legal. Documento real contém ajustes e crédito anterior, campos que um somatório de notas não representa. Não anunciar homologação oficial, apuração fiscal completa ou cobertura de todos os tributos.

## 4. Inventário histórico dos 18 módulos (S1)

Controles/falhas abaixo são números do catálogo anterior, não medição nova nem percentual de equivalência funcional.

| Executável | Finalidade | Versão | Interfaces | Controles | Falhas de descompilação |
|---|---|---|---:|---:|---:|
| CTB010100.EXE | Plano de Contas | 5.85 | 24 | 687 | 38 |
| CTB020100.EXE | Digitação de Lançamentos Contábeis | 5.56 | 23 | 871 | 79 |
| CTB020400.EXE | Razão Contábil | 5.105 | 11 | 612 | 46 |
| CTB020600.EXE | Diário Geral | 5.52 | 18 | 1084 | 34 |
| CTB020700.EXE | Razão Contábil por Centro de Custo | 5.12 | 11 | 512 | 33 |
| CTB020800.EXE | Diário Consolidado | 5.46 | 19 | 1491 | 31 |
| CTB020900.EXE | Conciliação Contábil | 5.92 | 17 | 414 | 76 |
| CTB020900A.EXE | Conciliação Contábil | 5.42 | 12 | 368 | 23 |
| CTB021300.EXE | Balancete de Verificação em Tela | 5.23 | 12 | 599 | 29 |
| CTB021400.EXE | Balancete de Verificação | 5.130 | 10 | 952 | 76 |
| CTB021500.EXE | Balancete de Verificação em Tela por Centro de Custo | 5.07 | 9 | 353 | 20 |
| CTB021700.EXE | Balancete por Centro de Custo Sintético Consolidado | 5.13 | 6 | 187 | 9 |
| CTB030200.EXE | Relatórios do Balanço | 5.189 | 13 | 1495 | 67 |
| LFSCTAPAGREC.EXE | Contas a Pagar e Receber | 5.87 | 14 | 450 | 59 |
| LFSDOCTOS.EXE | Digitação de Documentos Fiscais | 5.701 | 52 | 5285 | 450 |
| LFSLIVROS.EXE | Impressão de Documentos Fiscais | 5.146 | 9 | 201 | 499 |
| LFSLIVROSAPUR.EXE | Livros de Apuração | 5.25 | 6 | 88 | 30 |
| PRG010100.EXE | Cadastro de Empresas | 5.178 | 15 | 228 | 49 |

## 5. Filtros e controles atribuídos ao legado: origem e lacunas

Esta tabela registra S4, consultada na primeira inspeção. A seção 9 acrescenta confirmação direta de controles, dimensões e captions dos formulários recuperados; opções dinâmicas, eventos e dependências continuam sem confirmação funcional.

| Família | Campos/controles registrados | Localizador histórico | Falta para reprodução fiel |
|---|---|---|---|
| Razão | Razão analítico e Planilha Excel | CTB020400/frmCTB020401, 402, 403 | Todos os filtros e colunas por variante; só D2 dá uma saída concreta. |
| Diário Geral | Mês, folha e paisagem | CTB020600/frmCTB020601 e frmCTB0206G1 | PDFs dos modelos I–V; política de partidas/contrapartidas e paginação. |
| Razão por centro | Centro e intervalo | CTB020700/frmCTB020701 | PDF e definição da filtragem por partida/lançamento. |
| Diário Consolidado | Agrupamentos e filiais | CTB020800/frmCTB020801; print 040046 | Print original, PDFs e critérios de consolidação/eliminações. |
| Balancete em tela | Cálculo/consulta, acesso/classificador | CTB021300/frmCTB021301 e 303 | Colunas e opções completas dos modelos Normal/ANS/Centro. |
| Balancete de Verificação | DRE e conta com saldo zero | CTB021400/frmCTB021401:69,275 | PDF, regra de zero/sintéticas/redutoras e termos/assinaturas. |
| Balancete por centro | Consulta por centro | CTB021500/frmCTB021501 | PDF, diferenças entre variantes ANS e padrão. |
| Balancete sintético consolidado por centro | Redutoras e período | CTB021700/frmCTB021701 | Árvore, natureza e consolidação comprovadas. |
| Relatórios do Balanço | Balanço/DRE; termo; seleção de sócios | CTB030200/frmCTB030201:3,68 e S2 | PDF por peça, encerramento, natureza, assinaturas e comparativos. |
| Livros fiscais | Manutenção, observação da NF, observações dos livros, pesquisa, visualização | LFSLIVROS/frmDig, frmLFS000133, frmObs, frmPesq, frmPrint | Tela de seleção de livros e relação completa dos modelos. |
| Apuração fiscal | Apuração centralizada | LFSLIVROSAPUR/frmLFS000134:230 | Motor fiscal, perfis e dependências externas. |
| Financeiro | Relatórios, consultas, baixas, histórico do Livro Razão | LFSCTAPAGREC/frmLista, frmCons, frmBaixa, frmHisRaz | Tipos de relatórios, filtros, grades e PDFs não demonstrados. |
| Conciliação | V4: filtros e parâmetros; versão A: colunas, documento, histórico, data e conta | CTB020900/frmFiltro, frmParametrosConciliacao; CTB020900A/frmCtbVisualizarColunas e controles uct | Não presumir que relatório de títulos reproduza conciliação contábil. |

## 6. Condições de aceite e limites

1. Cada modelo deve declarar qual fonte e variante reproduz. Um nome de módulo não prova todos os modelos de impressão.
2. Títulos e colunas podem ser reproduzidos com a evidência acima. Dimensões exatas, fontes, quebras e posicionamento exigem comparação de páginas renderizadas no mesmo tamanho e teste de documentos longos/multilinha.
3. Regra matemática deve ser implementada e testada separadamente: saldo anterior + movimento, natureza D/C, débito/crédito, rateios/centros, cancelamentos, ajustes e transporte. Formulário recuperado não contém prova suficiente do algoritmo.
4. Não substituir coluna desconhecida por zero silenciosamente; marcar dado não disponível ou bloquear perfil que dependa dele. Campo vazio na amostra não prova que sempre deve ficar vazio.
5. Nenhum PDF direto de Diário, Balancete, Balanço, DRE, razão por centro, financeiro ou conciliação foi identificado nesta revisão focal. Variantes gráficas/matriciais/ANS são existência documentada, não desenhos integralmente recuperados.
6. S5 documenta comparação monetária anterior apenas de um Razão. Não estender esse resultado aos outros modelos nem afirmar teste novamente executado.
7. Próximos insumos: originais do ZIP de engenharia reversa e prints; um PDF vazio/anonimizado de cada variante e tela de parâmetros; confirmação de autoria dos livros históricos; critérios de aceite contábeis/fiscais. Nenhum executável legado precisa ser executado para aproveitar esses materiais.

## 7. Identidade dos arquivos diretos

SHA-256 calculado nesta inspeção; tamanho de página obtido do PDF. Identifica o exemplar, não atesta autoria/homologação.

| Fonte | Páginas | Página 1 (pt), rotação | SHA-256 |
|---|---:|---|---|
| D2 | 7 | 794 × 1122; 0° | `0b04ae08eb476aa8ad78df6409c65163dbbd9a71b51d220455e12c1bc4fbd5aa` |
| D3 | 649 | 1122 × 794; 0° | `231475b106abf9f22349ad7708019dbeb133e621e77781cfd6e18e897e98942c` |
| D4 | 57 | 595 × 842; 90° | `359724f034f72203f6ec432f56af632a8b2083254bb33ba59b1c32e4805c2404` |
| D5 | 175 | 595 × 842; 90° | `7965a2f9da30fc2e88140480c22c05891639b5199efb7b2beeb0e918de3824a8` |
| D6 | 2 | 595 × 842; 0° | `f1d886c79d5ff223aebf0b52b44dae2aa4fea2f6da5a12c229dfeea1b80f4c44` |

## 8. Apêndice: títulos recuperados de formulários de relatórios (S2)

Transcrição do primeiro rótulo no catálogo, com localizador de origem. Não são todos os rótulos, nem todos os controles. `linha` refere-se ao arquivo original ausente, não a este documento. O CSV completo mantém as 281 entradas.

| Arquivo de origem | Primeiro rótulo | Linha |
|---|---|---:|
| `CTB020400/interfaces_vb6/frmCTB020401.frm` | Razao Analítico | 3 |
| `CTB020400/interfaces_vb6/frmCTB020402.frm` | Razão Analítico | 3 |
| `CTB020400/interfaces_vb6/frmCTB020403.frm` | Planilha Excel | 3 |
| `CTB020400/interfaces_vb6/frmCTB0204G1.frm` | Razão Analítico - Gráfica(paisagem) | 3 |
| `CTB020400/interfaces_vb6/frmCTB0204G2.frm` | Razão Analítico - Matricial | 3 |
| `CTB020400/interfaces_vb6/frmCTB0204G3.frm` | Extrato - Gráfico (paisagem) | 3 |
| `CTB020400/interfaces_vb6/frmCTB0204G4.frm` | Extrato - Matricial | 3 |
| `CTB020400/interfaces_vb6/frmCTB0204G5.frm` | Razão Analítico - Gráfica(retrato) | 3 |
| `CTB020400/interfaces_vb6/frmCTB0204G6.frm` | Extrato - Gráfica(retrato) | 3 |
| `CTB020400/interfaces_vb6/frmCtbRazSoc.frm` | Razão Social sem Abreviatura | 3 |
| `CTB020600/interfaces_vb6/frmCTB020601.frm` | Nome da Rotina - Versão | 3 |
| `CTB020600/interfaces_vb6/frmCTB020602.frm` | Planilha Excel | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G1.frm` | Gabarito (Paisagem) - Modelo I | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G2.frm` | Gabarito (Paisagem) -  Modelo II | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G3.frm` | Gabarito (Matricial) - Modelo I | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G4.frm` | Gabarito (Matricial) - Modelo II | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G5.frm` | Gabarito (Retrato) - Modelo I | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G6.frm` | Gabarito (Retrato) - Modelo II | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G7.frm` | Gabarito (Retrato) - Modelo III | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G8.frm` | Gabarito (Retrato)  - Modelo IV | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206G9.frm` | Gabarito (Paisagem) -  Modelo IV | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206GA.frm` | Gabarito (matricial) -  Modelo IV | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206GB.frm` | Gabarito (Paisagem) - Modelo III | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206GC.frm` | Gabarito (Matricial) - Modelo III | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206GD.frm` | Gabarito (Retrato) - Modelo V | 3 |
| `CTB020600/interfaces_vb6/frmCTB0206GE.frm` | Gabarito (Matricial) - Modelo V | 3 |
| `CTB020600/interfaces_vb6/frmCtbRazSoc.frm` | Razão Social sem Abreviatura | 3 |
| `CTB020700/interfaces_vb6/frmCTB020701.frm` | Razão por Centro de Custo | 3 |
| `CTB020700/interfaces_vb6/frmCTB020702.frm` | &Anterior | 51 |
| `CTB020700/interfaces_vb6/frmCTB020703.frm` | Planilha Excel | 3 |
| `CTB020700/interfaces_vb6/frmCTB0207G1.frm` | Razão - Gráfico (paisagem) | 3 |
| `CTB020700/interfaces_vb6/frmCTB0207G2.frm` | Razão - Matricial | 3 |
| `CTB020700/interfaces_vb6/frmCTB0207G3.frm` | Extrato - Gráfico (paisagem) | 3 |
| `CTB020700/interfaces_vb6/frmCTB0207G4.frm` | Extrato - Matricial | 3 |
| `CTB020700/interfaces_vb6/frmCTB0207G5.frm` | Razão - Gráfico (retrato) | 3 |
| `CTB020700/interfaces_vb6/frmCTB0207G6.frm` | Extrato - Gráfico (retrato) | 3 |
| `CTB020700/interfaces_vb6/frmCtbRazSoc.frm` | Razão Social sem Abreviatura | 3 |
| `CTB020800/interfaces_vb6/frmCTB020801.frm` | Diário Consolidado | 3 |
| `CTB020800/interfaces_vb6/frmCTB020802.frm` | Planilha Excel | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G1.frm` | Gabarito (Paisagem) - Modelo I | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G2.frm` | Gabarito (Paisagem) - Modelo II | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G3.frm` | Gabarito (Matricial) - Modelo I | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G4.frm` | Gabarito (Matricial) - Modelo II | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G5.frm` | Gabarito (Retrato) - Modelo I | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G6.frm` | Gabarito (Retrato) - Modelo II | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G7.frm` | Gabarito (Retrato) - Modelo III | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G8.frm` | Gabarito (Paisagem) - Modelo III | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208G9.frm` | Gabarito (Matricial) - Modelo III | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208GA.frm` | Gabarito (Retrato) - Modelo IV | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208GB.frm` | Gabarito (Paisagem) - Modelo IV | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208GC.frm` | Gabarito (Matricial) - Modelo IV | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208GD.frm` | Gabarito (Retrato) - Modelo V | 3 |
| `CTB020800/interfaces_vb6/frmCTB0208GE.frm` | Gabarito (Matricial) - Modelo V | 3 |
| `CTB020800/interfaces_vb6/frmCtbRazSoc.frm` | Razão Social sem Abreviatura | 3 |
| `CTB020800/interfaces_vb6/frmMsgLeiSA.frm` | Atenção | 3 |
| `CTB021300/interfaces_vb6/frmCTB021301.frm` | Balancete em tela | 3 |
| `CTB021300/interfaces_vb6/frmCTB021302.frm` | Processando os dados | 3 |
| `CTB021300/interfaces_vb6/frmCTB021303.frm` | Consulta dos Valores Calculados | 3 |
| `CTB021300/interfaces_vb6/frmCTB021304.frm` | Impressão | 3 |
| `CTB021300/interfaces_vb6/frmCTB021305.frm` | Processando planilha Excel | 3 |
| `CTB021300/interfaces_vb6/frmCTB0213G1.frm` | Gabarito Normal  (retrato/matricial) | 3 |
| `CTB021300/interfaces_vb6/frmCTB0213G2.frm` | Gabarito ANS Normal  (paisagem) | 3 |
| `CTB021300/interfaces_vb6/frmCTB0213G3.frm` | Gabarito C/Custo (retrato/matricial) | 3 |
| `CTB021300/interfaces_vb6/frmCTB0213G4.frm` | Gabarito ANS C/Custo (paisagem) | 3 |
| `CTB021300/interfaces_vb6/frmCTB0213G5.frm` | Gabarito Normal  (paisagem) | 3 |
| `CTB021300/interfaces_vb6/frmCTB0213G6.frm` | Gabarito C/Custo (paisagem) | 3 |
| `CTB021400/interfaces_vb6/frmCTB021401.frm` | Balancete de Verificação - Padrão DOS | 3 |
| `CTB021400/interfaces_vb6/frmCTB021402.frm` | Calculando valores | 3 |
| `CTB021400/interfaces_vb6/frmCTB021403.frm` | Gerando Planilha Excel | 3 |
| `CTB021400/interfaces_vb6/frmCTB021404.frm` | Parametrização do Termo de Responsabilidade | 3 |
| `CTB021400/interfaces_vb6/frmCTB0214G1.frm` | Gabarito - gráfico | 3 |
| `CTB021400/interfaces_vb6/frmCTB0214G2.frm` | Gabarito - matricial | 3 |
| `CTB021400/interfaces_vb6/frmCTB0214G3.frm` | Gabarito (paisagem) | 3 |
| `CTB021400/interfaces_vb6/frmParametros.frm` | Parâmetros | 3 |
| `CTB021400/interfaces_vb6/frmSelecaoSocios.frm` | Consulta de Sócios | 3 |
| `CTB021500/interfaces_vb6/frmCTB021501.frm` | Balancete em Tela por Centro de Custo | 3 |
| `CTB021500/interfaces_vb6/frmCTB021502.frm` | Processamento | 3 |
| `CTB021500/interfaces_vb6/frmCTB021503.frm` | Consulta dos Valores Calculados | 3 |
| `CTB021500/interfaces_vb6/frmCTB021504.frm` | Impressão | 3 |
| `CTB021500/interfaces_vb6/frmCTB021505.frm` | Processando Planilha Excel | 3 |
| `CTB021500/interfaces_vb6/frmCTB0215G1.frm` | Gabarito de Impressão - gráfica(retrato)/matricial | 3 |
| `CTB021500/interfaces_vb6/frmCTB0215G2.frm` | Gabarito de Impressão - gráfica(ANS) | 3 |
| `CTB021500/interfaces_vb6/frmCTB0215G3.frm` | Gabarito - gráfico(paisagem) | 3 |
| `CTB021700/interfaces_vb6/frmCTB021701.frm` | Nome da Rotina - Versão | 3 |
| `CTB021700/interfaces_vb6/frmCTB021702.frm` | Processamento | 3 |
| `CTB021700/interfaces_vb6/frmCTB021703.frm` | Gerando Planilha Excel | 3 |
| `CTB021700/interfaces_vb6/frmCTB0217G1.frm` | Gabarito de Impressão-Retrato | 3 |
| `CTB021700/interfaces_vb6/frmCTB0217G2.frm` | Gabarito de Impressão-Paisagem | 3 |
| `CTB030200/interfaces_vb6/frmCTB030201.frm` | Relatórios do Balanço | 3 |
| `CTB030200/interfaces_vb6/frmCTB030202.frm` | Calculando Valores | 3 |
| `CTB030200/interfaces_vb6/frmCTB030203.frm` | Gerando Planilha Excel | 3 |
| `CTB030200/interfaces_vb6/frmCTB030204.frm` | Parametrização do Termo de Responsabilidade | 3 |
| `CTB030200/interfaces_vb6/frmCTB0302G1.frm` | Balancete Analítico de Encerramento do Exercício Social (paisagem e matricial) | 3 |
| `CTB030200/interfaces_vb6/frmCTB0302G2.frm` | Gabarito - ANS | 3 |
| `CTB030200/interfaces_vb6/frmCTB0302G3.frm` | Gabarito gráfico (retrato) | 3 |
| `CTB030200/interfaces_vb6/frmCTB0302G4.frm` | Gabarito (paisagem) - Razão Social (terceiro) | 3 |
| `CTB030200/interfaces_vb6/frmCTB0302G5.frm` | Gabarito-Matricial Sintético | 3 |
| `CTB030200/interfaces_vb6/frmDemonstrativo.frm` | Demonstrativo de Balanço | 3 |
| `CTB030200/interfaces_vb6/frmParametros.frm` | Parâmetros | 3 |
| `CTB030200/interfaces_vb6/frmSelecaoSocios.frm` | Consulta de Socios | 3 |
| `LFSLIVROS/interfaces_vb6/frmDig.frm` | Manutenção | 3 |
| `LFSLIVROS/interfaces_vb6/frmEContador.frm` | eContador | 3 |
| `LFSLIVROS/interfaces_vb6/frmLFS000133.frm` | Imprime Observação da NF | 56 |
| `LFSLIVROS/interfaces_vb6/frmME.frm` | Movimentos de Saídas da ME | 3 |
| `LFSLIVROS/interfaces_vb6/frmObs.frm` | Observações referentes aos Livros | 3 |
| `LFSLIVROS/interfaces_vb6/frmPesq.frm` | Pesquisa | 3 |
| `LFSLIVROS/interfaces_vb6/frmPrint.frm` | Visualização | 3 |
| `LFSLIVROS/interfaces_vb6/frmWait.frm` | Aguarde... | 3 |
| `LFSLIVROSAPUR/interfaces_vb6/frmEContador.frm` | eContador | 3 |
| `LFSLIVROSAPUR/interfaces_vb6/frmLFS000134.frm` | &Empresa | 83 |
| `LFSLIVROSAPUR/interfaces_vb6/frmPesq.frm` | Pesquisa | 3 |
| `LFSLIVROSAPUR/interfaces_vb6/frmPrint.frm` | Sem Caption estático |  |
| `LFSLIVROSAPUR/interfaces_vb6/frmWait.frm` | Aguarde o Processamento . . . | 3 |

## 9. Verificação complementar na Space e no pacote original

Busca focal realizada em 09/11/2026. Foram consultados nome exato `Projetos_Engenharia_Reversa.zip`, sinônimos `Projetos Engenharia Reversa`, `Prosoft`, `Relatórios`, `print Prosoft` e títulos `Captura de tela`/`Engenharia`. A consulta inicial por conteúdo retornou sobretudo fragmentos do MHTML; a consulta refinada por metadados/títulos retornou **8 candidatos**, sem continuação: ZIP de engenharia reversa e seu SHA256, prompt revisado, pacote de integração DIX, Prosoft.zip e três MHTMLs. Não é busca universal por todos os anexos de todas as conversas, nem prova de inexistência de prints com outro nome.

Original confirmado: **Projetos_Engenharia_Reversa.zip**, 419.569.994 bytes, identidade Space `libfile_26684133235c81919e9d531dde28d7ff`, arquivo `file_000000000ad481fdb5dbb92f77a9d3e1`, disponibilizado em 06/11/2026. SHA256 acompanhante: `libfile_b8221e2d318c8191bf0d3bf459fea493`. Ambos foram materializados pelo mecanismo suportado em `prosoft_library_originals_20261109/`, fora do checkout. SHA256 recalculado do ZIP: `fefd594930d9dc5fae924d51ef5e0e6c60152a00e4c030f11611418e42831872`, igual ao acompanhante e a S3.

A listagem direta tem **7.871 entradas**, incluindo **277 .frm, 4 .ctl, 281 .formbin, 210 .frx e 18 .exe**. Não há `.bas` nem imagens `.png`/`.jpg` ou PDFs. Foram lidos seletivamente README, formulários e gabaritos; os hashes dos 18 EXEs também foram recalculados dos bytes no ZIP e todos coincidiram com S3. Nenhum programa, script de recuperação ou binário do ZIP foi executado. Não se importaram arquivos do pacote para o repositório.

O README do pacote afirma explicitamente que os projetos VB6 são interfaces parciais, **sem código funcional dos eventos**, e que não foram recuperados 18 projetos-fonte originais completos/recompiláveis. Pseudocódigo C, assembly e interfaces recuperadas não são equivalentes a fontes originais nem garantem algoritmo tributário/contábil.

### 9.1 O que a nova evidência acrescenta

- **Diário CTB020600:** seleção de modelo, título, intervalo, folha/página inicial, limite de páginas, retrato, razão social/terceiros, data de emissão, nova folha por mês, totalização diária e resumo de contas. Gabaritos Modelo I a V e paisagem/retrato/matricial confirmados nos arquivos, não apenas no CSV histórico.
- **Balancete CTB021400:** saídas de Balanço, resultado e custos dos serviços/mercadorias/produtos; saldo zero, redutoras, grupos/resumo, saldo inicial/final de resultado, terceiros, matriz/filiais, dados do contador, notas explicativas, termos, assinaturas e NIRE. Esses controles **não estão automaticamente implementados** pelo PDF genérico ou por um layout com as mesmas colunas.
- **Balanço CTB030200:** adicionalmente indicadores `+ / -` ou `D / C`, nova folha por grupo, plano especial, centros de custos sintéticos, analíticas com movimento, cálculo do resultado pelos saldos, passivo a descoberto e patrimônio líquido.
- **LFSLIVROS:** ISS modelos 51/53/56, Livro Registro de Entradas/Saídas e Mapa Resumo ECF aparecem em captions; opções de resumo CFO/UF/IVA GO, autenticação, número do livro, subtotal diário, totalização IPI por decêndio e impressão sem movimento. Portanto o catálogo operacional atual não cobre integralmente todos os tipos e opções históricos.
- **LFSLIVROSAPUR:** LRA ICMS, apuração centralizada, substituição tributária, demonstrativo dos recolhimentos, entradas/saídas separadas, decêndio e autenticação são controles diretos. Isso não recupera seus cálculos.
- **Geometria verificável:** gabaritos contêm `Left`, `Top`, `Width`, `Height`, fonte e tamanho. No CTB020600/frmCTB0206G1, `DATA` tem Left=120, Top=1710, Width=480, Height=240 e fonte Courier New 9.75. São medidas VB6 do formulário (ScaleMode=1 no formulário principal), não um PDF emitido nem prova de margens finais da impressora.
- **Colunas dos gabaritos:** Diário Modelo I explicita DATA, CONTA DEVEDORA, CONTA CREDORA, HISTÓRICO, VALOR. CTB030200/frmCTB0302G1 explicita Acesso, Classificador, Nome da Conta, Saldo Inicial, Mov.Débito, Mov.Crédito, Saldo Final, Terc, C/Custo, Resumo do Balancete, Resultado do Período e Diferença. O layout em partidas separadas da implementação nova não deve ser chamado de reprodução de todos os modelos de Diário.

Conclusão atualizada: a lacuna de acesso ao ZIP foi resolvida e há base direta para refinamentos de interface/layout. **Não** foi encontrado novo exemplar impresso dentro do pacote e **não** há fonte de eventos completa que permita adotar algoritmos originais. A implementação e os testes atuais não devem ganhar automaticamente o status “idêntico à Prosoft”. Novas famílias/controles exigem decisão de escopo, implementação e validação separadas.

### 9.2 Captions dos formulários prioritários diretamente lidos

Localizadores relativos a `Projetos_Engenharia_Reversa/projetos/`. Linhas e textos extraídos dos `.frm` em Windows-1252; rótulos repetidos e grafia original preservados. São captions estáticos, não listas dinâmicas completas nem comportamento dos eventos.

#### `CTB020600/interfaces_vb6/frmCTB020601.frm`

SHA256: `839481b3fe7cfc71cb07ae1ca7ec4bd3555ade31d1a47a3e3f1839a3dc519d0b`.

| Linha | Caption literal |
|---:|---|
| 3 | Nome da Rotina - Versão |
| 65 | Ocultar código da empresa |
| 75 | Iniciar uma nova folha a cada mês |
| 84 | Página |
| 93 | Folha |
| 103 | Imprimir Data de Emissão |
| 113 | Imprimir razão social |
| 123 | Imprimir terceiros |
| 155 |  Protocolo  |
| 173 | Gerar movimento |
| 244 | Imprimir em formato retrato |
| 265 |  Selecione a Opção  |
| 297 | Totalizar ao final de cada dia |
| 307 | Imprimir resumo das contas |
| 346 | Emitir como: |
| 356 | Limite de páginas |
| 366 | Título do relatório |
| 377 | Até |
| 397 | A partir |
| 417 | Dia/Mês |
| 428 | Dia/Mês |
| 439 | Numerar folhas a partir de: |
| 450 | Período |
| 476 | Modelo do Diário  |
| 488 | &Opções |
| 491 | Selecionar Nova Empresa |
| 495 | - |
| 499 | &Sair |
| 503 | &Ferramentas |
| 506 | Calculadora |
| 510 | Calendário |
| 514 | - |
| 518 | Verificar Configuração de Pastas |
| 523 | &Ajuda |
| 526 | Ajuda do Diário Individual |

#### `CTB021400/interfaces_vb6/frmCTB021401.frm`

SHA256: `4fa6e97c24285d1d0abc7992d9ec96239ddbf626ceb6fa521ef7d2597ea00e7e`.

| Linha | Caption literal |
|---:|---|
| 3 | Balancete de Verificação - Padrão DOS |
| 36 | para mais detalhes. |
| 48 | Clique aqui |
| 69 | Inconsistências na DRE! |
| 142 |  Protocolo  |
| 160 | Gerar movimento |
| 170 |  Selecione a opção |
| 202 | Balanço patrimonial |
| 221 | Gerar assinatura(s) digitalizada(s) |
| 255 | Imprimir termo de reconhecimento |
| 265 | Passivo a descoberto |
| 275 | Não imprimir contas com saldo zero |
| 365 | Ordem de impressão |
| 376 | Título do Balanço:  |
| 386 | Patrimonio Lï¿½quido |
| 396 | Imprimir contas atï¿½:  |
| 407 |  Selecione a moeda  |
| 433 | Imprimir |
| 452 | Balancete |
| 472 | Demonstrações |
| 491 | Balanço patrimonial |
| 510 | Demonstração do custo dos serviços |
| 530 | Demonstração do custo das mercadorias |
| 550 | Demonstração do custo dos produtos |
| 570 | Demosntração do resultado |
| 591 | Demonstrações |
| 610 | Imprimir códigos das contas |
| 621 | Gerar assinatura(s) digitalizada(s) |
| 630 | Imprimir termo de reconhecimento |
| 678 | Geral |
| 697 | Opções |
| 714 | Ocultar código da empresa |
| 724 | Rodapé para Chancela Digital |
| 734 | Página |
| 745 | Folha |
| 757 | Valores de estoque |
| 775 | Manutenção de Saldos |
| 786 | Digitação de Estoques |
| 797 | Imprimir Termo de Responsabilidade |
| 814 | Imprimir Nire no cabeçalho |
| 824 | Imprimir notas explicativas |
| 835 | Imprimir contas com terceiros sinteticamente |
| 844 | Imprime termo em todas as páginas |
| 855 | Imprimir razão social do terceiro |
| 865 | Transportar resultado do período para o passivo |
| 876 | Zerar saldo inicial das contas de resultado |
| 887 | Abrir arquivo consolidado (Matriz/Filiais) |
| 1010 | Emitir como:  |
| 1021 | Ordem dos termos: |
| 1032 | Mês |
| 1043 | Configurações |
| 1142 | Numerar folhas a partir de |
| 1153 | Data da emissão |
| 1165 | Período de Apuração |
| 1302 | Data do encerramento  |
| 1313 | Até o dia/mês |
| 1324 | A partir do dia/mês |
| 1337 | Balancete |
| 1356 | Diminuir Tamanho da Fonte (Impressão com Valores na casa dos Bilhões) |
| 1366 | Gerar assinatura(s) digitalizada(s) |
| 1393 | Deduzir valores de contas redutoras |
| 1403 | Imprimir relatório de pendências |
| 1413 | Imprimir somente os grupos |
| 1423 | Zerar saldo final das contas de resultado |
| 1433 | Imprimir dados do contador |
| 1443 | Imprimir somente resumo |
| 1680 | Título do Balancete:  |
| 1695 | Opções |
| 1698 | Selecionar Nova Empresa |
| 1702 | - |
| 1707 | Imprimir leiaute |
| 1711 | - |
| 1715 | &Sair |
| 1719 | &Ferramentas |
| 1722 | Calculadora |
| 1726 | Calendário |
| 1730 | Pendências |
| 1734 | - |
| 1738 | Configuração de Pastas |
| 1743 | &Ajuda |
| 1746 | Ajuda dos Relatórios do Balanço - Mod. II |

#### `CTB030200/interfaces_vb6/frmCTB030201.frm`

SHA256: `d9f816ad6c57d8cda2986443d1bf1c551b0ec8f02557203990b07f97d3375a6d`.

| Linha | Caption literal |
|---:|---|
| 3 | Relatórios do Balanço |
| 35 | para mais detalhes. |
| 47 | Clique aqui |
| 68 | Inconsistências na DRE ! |
| 81 |  Selecione a moeda  |
| 118 | Balancete |
| 137 | Inviabilizar espaços em branco |
| 147 | Diminuir Tamanho da Fonte (Movimento com valores em bilhões) |
| 156 | Gerar assinatura(s) digitalizada(s) |
| 173 | Iniciar uma nova folha a cada grupo |
| 184 | Imprimir dados do contador |
| 194 | Zerar saldo final das contas de resultado |
| 204 | Imprimir somente resumo |
| 214 | Imprimir somente os grupos |
| 224 | Calcula resultado com base nos saldos do balancete |
| 254 | Imprimir relatório de pendências |
| 264 | Deduzir valores de contas redutoras |
| 293 |  Indicadores  |
| 302 | + / - |
| 313 | D / C |
| 531 | Título do Relatório:  |
| 541 | Imprimir contas até:  |
| 582 |  Protocolo  |
| 600 | Gerar movimento |
| 610 |  Selecione a opção  |
| 642 | Demonstrações |
| 661 | Gerar assinatura(s) digitalizada(s) |
| 670 | Imprimir códigos das contas |
| 681 | Imprimir termo de reconhecimento |
| 729 | Imprimir |
| 748 | Balancete |
| 759 | Demonstrações |
| 769 | Balanço patrimonial |
| 779 | Custo dos serviços |
| 799 | Custo das mercadorias |
| 819 | Custo dos produtos |
| 839 | Resultado |
| 859 | Selecionar |
| 869 | Geral |
| 888 | Opções |
| 905 | Ocultar código da empresa |
| 915 | Rodapé para Chancela Digital |
| 925 | Abrir arquivo consolidado (Matriz/Filiais) |
| 935 | Zerar saldo inicial das contas de resultado |
| 946 | Imprimir contas com terceiros sinteticamente |
| 956 | Imprimir centros de custos conforme cadastro |
| 966 | Imprimir contas com c/custo sinteticamente |
| 976 | Imprimir conforme plano especial |
| 986 | Imprimir contas com c/custos e terceiros sinteticamente |
| 996 | Transportar resultado do período para o passivo |
| 1007 | Imprimir em formato retrato |
| 1017 | Imprimir NIRE no cabeçalho |
| 1027 | Imprimir notas explicativas |
| 1037 | Imprimir Termo de Responsabilidade |
| 1066 | Imprime termo em todas as páginas |
| 1075 | Imprimir razão social do terceiro |
| 1206 | Mês |
| 1216 | Ordem dos termos: |
| 1228 | Configurações |
| 1327 | Data da emissão  |
| 1338 | Numerar folhas a partir de |
| 1350 | Período de Apuração |
| 1487 | Data do encerramento  |
| 1498 | A partir do dia/mês  |
| 1509 | Até o dia/mês  |
| 1521 | Página |
| 1532 | Folha |
| 1544 | Emitir como:  |
| 1557 | Balanço Patrimonial |
| 1576 | Inviabilizar espaços em branco |
| 1586 | Iniciar uma nova folha a cada grupo |
| 1597 | Gerar assinatura(s) digitalizada(s) |
| 1606 | Imprimir contas analiticas com movimento |
| 1625 | Imprimir termo de reconhecimento |
| 1642 | Não imprimir contas com saldo zero |
| 1652 | Passivo a Descoberto |
| 1774 | Ordem de impressão: |
| 1785 | Imprimir contas até:  |
| 1796 | Patrimônio Líquido |
| 1806 | Passivo a Descoberto |
| 1817 | Título do Relatório:  |
| 1832 | Período de Apuração  |
| 1852 | &Opções |
| 1855 | Selecionar empresa |
| 1860 | - |
| 1864 | &Sair |
| 1868 | &Ferramentas |
| 1871 | Calculadora |
| 1875 | Calendário |
| 1879 | Pendências |
| 1883 | - |
| 1887 | Configuração Pasta |
| 1892 | &Ajuda |
| 1895 | Ajuda do Relatórios do Balanço - Mod. I |

#### `LFSLIVROS/interfaces_vb6/frmLFS000133.frm`

SHA256: `2ab43c8390e051823312f3d99625e700a9d62423ac0f88ab945cd64e8b94419d`.

| Linha | Caption literal |
|---:|---|
| 56 | Imprime Observação da NF |
| 66 | Reiniciar Páginas após Qtd Max |
| 91 | Livro ISS |
| 109 | Modelo 56 |
| 119 | Modelo 53 |
| 129 | Modelo 51 |
| 156 | Data: |
| 165 | Não Imprime Razão Social Fornecedor |
| 175 | Emite cabeçalho com Título Código Emitente |
| 184 | Específico 'ES' |
| 211 | Imprime Resumo por CFO |
| 221 | Imprime Resumo por UF |
| 232 | Imprime Pedido de Autenticação |
| 242 | Imprime Código da Empresa  |
| 251 | Imprime com traços |
| 261 | Imprime Resumo IVA (GO) |
| 283 | Imprime valores Zerados em Branco |
| 368 | Imprime Resumo das Observações |
| 378 | Imprime Dados do Contador |
| 387 | Grava Número do LRE do Cadastro de Bens do CIAP |
| 408 | Imprime Data e Assinatura |
| 428 | Número do Livro |
| 437 | Imprime sem Movimento |
| 446 | Imprime Sub-Total Diário |
| 455 | Totaliza IPI por Decêndio |
| 464 | Im&primir |
| 477 | Visualizar |
| 500 | Imprime Número de Lançamento |
| 546 | Modelo para Autorização |
| 555 | Modo de Impressão |
| 563 | Qtd. Máxima de Folhas por Livro |
| 572 | % para Alimentação |
| 584 | De |
| 595 | Termo de Impressão |
| 604 | Informe o Grupo |
| 613 | Data Pagto do Imposto |
| 623 | Numerar Folhas a Partir de |
| 634 | Número Inicial |
| 643 | Até |
| 653 | Modelo Para Impressão |
| 749 | Ano de Movimento |
| 813 | Empresa |
| 873 | &Arquivo |
| 877 | &Processar |
| 883 | &Cancelar |
| 887 | Sai&r |
| 891 | &Ferramentas |
| 894 | &Calculadora |
| 898 | C&alendário |
| 902 | &Verificar Configurações das Pastas |
| 906 | - |
| 911 | &Visualizar Impressão |
| 917 | Im&primir |
| 922 | Configurar &Impressora |
| 926 | - |
| 930 | &Digitação Saídas ME |
| 935 | Digitação das &Observações dos Livros |
| 941 | &Ajuda |
| 944 | &Sobre Impressão dos Livros Fiscais |

#### `LFSLIVROS/interfaces_vb6/frmObs.frm`

SHA256: `4fbde993e44b501942df9d6f8253649de7172c3cb31a457245200bf8d4b14d95`.

| Linha | Caption literal |
|---:|---|
| 3 | Observações referentes aos Livros |
| 35 | Livro Serviços ISS Modelo 56 |
| 44 | Livro Serviços ISS |
| 53 | Livro Serviços ISS Modelo 51 |
| 62 | Mapa Resumo ECF |
| 71 | Livro Serviços ISS Modelo 53 |
| 80 | Livro Registro de Saídas |
| 89 | Livro Registro de Entradas |
| 139 | Observações |
| 150 | &Arquivo |
| 153 | &Salvar |
| 157 | &Cancelar |
| 160 | - |
| 164 | Sai&r |

#### `LFSLIVROSAPUR/interfaces_vb6/frmLFS000134.frm`

SHA256: `61a86e013f684f261625de8965c4e3a381c14db75a01da8ac034b60ebafa0271`.

| Linha | Caption literal |
|---:|---|
| 83 | &Empresa |
| 188 | Pedidos de Autenticação |
| 195 | Formulários LRA ICMS |
| 203 | Livro Fiscal |
| 220 | Nº Livro |
| 230 | Apuração Centralizada |
| 247 | Imprimir |
| 259 | Visualizar |
| 271 | Imprime: |
| 280 | Não Imprime Resumo CFOP por Substituição Tributária |
| 289 | Imprime Código da Empresa |
| 298 | LRA - Subst.Trib. - Imprime só com valores |
| 307 | Demonstrativo dos Recolhimentos a Efetuar |
| 316 | Demonstrativo de Entradas e Saídas Separadamente |
| 325 | Modelo para Autorização |
| 334 | Resumo das Observações |
| 344 | Específico 'ES' |
| 372 | Decêndio |
| 389 | Opções |
| 445 | Período Inicial |
| 456 | Período Final |
| 466 | Numerar folhas a partir de |
| 477 | Termo de Impressão |
| 499 | Modelo Para Impressão |
| 509 | Até |
| 531 | &Arquivo |
| 534 | &Sair |
| 538 | &Ferramentas |
| 541 | &Calculadora |
| 545 | C&alendário |
| 549 | &Verificar configurações das Pastas |
| 553 | - |
| 557 | Vi&sualizar Impressão |
| 561 | Im&primir |
| 565 | Configurar &Impressora |
| 570 | &Ajuda |
| 573 | &Sobre Impressão dos Livros de Apuração |
