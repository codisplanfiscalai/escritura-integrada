# Relatórios fiscais e contábeis: modelos e validação

## Operação

Em Contábil ou Fiscal → Relatórios, selecione o relatório, o período e os filtros pertinentes. O campo **Modelo de impressão** oferece o modelo genérico Escritura e os modelos específicos disponíveis para aquele relatório. Informe a folha inicial e gere a consulta antes de exportar ou abrir a prévia.

A tabela, os totalizadores e as ações de CSV, Excel, PDF e prévia ficam vinculados aos filtros da última consulta gerada. Alterar controles não muda silenciosamente o destino da exportação. Para aplicar os novos filtros, gere outra consulta. Trocar empresa, exercício ou relatório invalida a consulta anterior e fecha a prévia.

**Prévia PDF** abre o documento em uma janela que pode ser maximizada, restaurada e fechada, inclusive com Escape. O leitor PDF do navegador pode oferecer suas próprias ações. **Abrir / imprimir** abre o PDF no leitor disponível no sistema; no aplicativo Qt, utiliza o fluxo nativo já existente. Um leitor PDF indisponível não transforma uma prévia vazia em sucesso: o link externo permanece disponível. Download e impressão preservam as permissões independentes de exportar/imprimir.

## Cobertura disponível

Há 17 modelos específicos selecionáveis:

- Contábeis: Diário Geral, Diário Consolidado, Razão Analítico Individual, Balancete, Movimentos por centro de custo, Balanço patrimonial e Demonstração do resultado.
- Fiscais: Documentos fiscais, Livro auxiliar de entradas, Livro auxiliar de saídas, Itens escriturados, Operações por CFOP, Operações por participante, Itens por NCM e CFOP, Bases e tributos declarados, Pendências de conferência e Livro auxiliar de apuração.

Os modelos contábeis organizam as respectivas colunas, contas/grupos/centros e totalizadores. Campos complementares ficam em anexo de conferência ligado ao número original do registro, sem serem descartados. Os fiscais separam identificação documental, itens, tributos e memórias de apuração conforme a natureza da consulta, em vez de comprimir todos os campos em uma única grade. Folhas, cabeçalhos e continuação acompanham a paginação.

O **Razão Analítico Individual** preserva o modelo baseado no PDF fornecido e sua comparação numérica histórica. Sua equivalência visual continua parcial: tipografia e quebras não são certificadas como idênticas. Os outros 16 modelos são impressões auxiliares específicas, **baseadas nos campos, sem homologação visual Prosoft**, identificadas assim no catálogo e nos PDFs. A matriz de fontes diretas, secundárias e lacunas está em [RELATORIOS_PROSOFT_REFERENCIAS.md](RELATORIOS_PROSOFT_REFERENCIAS.md).

## Filtros, cálculos e cuidados

- Valores monetários de domínio permanecem em centavos inteiros. O PDF apenas formata os valores consultados; não cria novas regras tributárias.
- No Razão, a pesquisa restringe movimentos exibidos. Os saldos preservam todos os movimentos da conta e centro no período, inclusive os não encontrados pela pesquisa. O aviso acompanha o PDF e os totais de débito/crédito abrangem as linhas exibidas.
- Entradas e Saídas incluem somente documentos escriturados, com operação fixa para o livro correspondente. Data de emissão e de escrituração são distintas. Bases e valores de ICMS/IPI são os declarados, com cobertura informada; não significam automaticamente imposto creditável/devido.
- CFOP e NCM nos relatórios documentais selecionam documentos que contenham aquela classificação. Seus totais permanecem integrais, sem rateio presumido. Nos relatórios por item, os filtros selecionam os próprios itens.
- Campos tributários ausentes ou ambíguos não viram zero. Um total conhecido sem cobertura completa não representa imposto total da empresa.
- Apuração considera as competências mensais das datas inicial/final, inclusive, e somente memórias finalizadas não estornadas. Não soma/compensa tributos diferentes. Filtros documentais incompatíveis são rejeitados, em vez de ignorados.
- Balanço e DRE exigem a classificação explícita das contas movimentadas. Não há encerramento anual automático, consolidação entre pessoas jurídicas nem eliminação intercompanhias.

## O que falta para identidade completa

Faltam exemplares impressos ou PDFs de cada variante com o mesmo conjunto de dados, filtros e versão da instalação Prosoft. A busca complementar na Space recuperou o pacote histórico de engenharia reversa e confirmou seu SHA256: os 18 binários e interfaces/gabaritos recuperados estão acessíveis para leitura estática. O pacote não contém prints/PDFs e não é um conjunto de fontes originais recompiláveis; os eventos VB6 não foram recuperados. Os controles diretamente verificados e as famílias ainda não implementadas estão detalhados na seção 9 de RELATORIOS_PROSOFT_REFERENCIAS.md. Os livros fiscais históricos P1/A, P2/A e P9 fornecem referências de campos e geometria, mas não comprovam fabricante nem regras fiscais completas. Permanecem fora desta entrega as variantes ISS 51/53/56, Mapa Resumo ECF, resumos IVA/UF/CFO, autenticação, IPI por decêndio, demonstrativos específicos de custos e opções avançadas de termos, assinaturas e consolidação; seus rótulos foram confirmados, não seus algoritmos.

Também não são implementados por esta etapa livros legais homologados, ECD/ECF, termos/assinaturas profissionais inventados, modelos especiais ANS, balanço comparativo, demonstrações não cobertas, dados de isentas/outras ou ajustes fiscais inferidos. A apresentação do P9 completo requer a origem detalhada de ajustes, códigos e demais quadros. A aplicação não declara que os 17 modelos esgotem o catálogo Prosoft.

## Verificação reproduzível

As verificações devem usar base descartável, nunca os dados operacionais do escritório:

```bash
export ESCRITURA_DATA_DIR=/tmp/escritura-relatorios-testes
npm --prefix frontend ci
npm --prefix frontend run build
python -m unittest discover -s tests -v
node --test frontend/tests/*.test.js
ESCRITURA_TEST_BROWSER=/usr/bin/chromium python scripts/browser_reports.py
```

Os testes específicos cobrem compatibilidade modelo/relatório, folha inicial e limite de paginação, PDFs vazios e multipáginas, campos extensos e caracteres especiais, saldos do Razão pesquisado, filtros fiscais efetivos, formatos de exportação e estado concorrente da interface. A aceitação nativa Windows/macOS/Qt e a homologação fiscal com a Prosoft continuam etapas distintas da validação local Linux/Chromium.
