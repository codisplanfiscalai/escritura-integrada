# Auditor Fiscal: experiência e modelos de relatório — 0.7.2

A correção 0.7.1 tornou os fluxos executáveis, mas não preservou a experiência analítica do Auditor original. Esta etapa corrige a apresentação dos resultados e os modelos exportados, sem trocar autenticação, persistência, filas ou regras fiscais.

## Referência efetivamente comparada

`auditorfiscal-1.2.2(1).zip`, SHA-256 `f738450837965543a190ac5304362abe868aee5dc9f35d19b8725a7dd6dbe2fb`.

| Recurso / origem no ZIP | Lacuna da integração 0.7.1 | Implementação 0.7.2 | Validação |
| --- | --- | --- | --- |
| `apps/web/src/views/AnalysisDetailView.vue` e `DashboardView.vue` | Histórico repetido acima de todas as consultas; indicadores reduzidos a texto | Área da auditoria selecionada, oito indicadores, conclusão, prioridades e análise crítica | Chromium: painel sem histórico sobreposto, totais, navegação e resoluções |
| `FiscalDocumentInspectionModal.vue` | Documento em detalhes expansíveis; participantes, transporte e cobrança agrupados genericamente | Inspeção modal por abas: documento, emitente, destinatário, produtos, totais, memória/achados, transporte, cobrança, informações, XML e auxiliar | Abertura por Enter, onze abas, filtro e inspeção de item, Esc e retorno de foco |
| Grade de documentos do original | Ausência de grade operacional | Grade com pesquisa, operação, situação, ordenação, paginação e contraparte por direção | Ordenação numérica, quatro entradas selecionadas de oito notas, filtro preservado após consulta |
| Críticas e análise do original | Evidência e ação dispersas; sem análise consolidada da base | Severidade, camadas, impacto, orientação, acesso à nota, tratamento e comparativo XML × recálculo | Tratamento persistido, prioridades atualizadas, origem fiscal/financeira/contábil inalterada |
| `services/fiscal-engine/app/reports/pdf_report.py` | PDF genérico sem painel, formação da base e análises de entradas/saídas separadas | Modelo paisagem com cabeçalho, indicadores, conclusão, prioridades, composição da base, comparativos, entradas/saídas totalizadas, críticas, classificação, conciliação, memória e fontes | Mesmo conjunto de dados passado ao exportador original e ao nativo; PDFs renderizados e inspecionados |
| `services/fiscal-engine/app/reports/excel_report.py` | Resumo em inglês; sem painel; itens sem componentes/diferenças; CST PIS/Cofins ausentes; largura uniforme | Painel executivo inicial, links de navegação, colunas recuperadas, tabelas filtráveis, congelamento, máscaras, destaques e impressão | Comparação de 672 células de negócio com o exportador original; códigos textuais, valores numéricos e abas legadas preservadas |
| Representação e acesso aos relatórios | Apenas links técnicos e hashes | Catálogo visual das seções, PDF dentro da tela, abertura/impressão, exportação Excel e revisões preservadas | Chromium abre PDF externo e embutido, baixa e reabre PDF/XLSX |

## Cálculos e integridade da apresentação

As agregações usam `Decimal`. Totais executivos excluem documentos cancelados ou fora do período. Comparativos usam somente os mesmos itens efetivamente recalculados: XML menos recálculo. Itens com cenário especial, grupo ausente ou sem XML não entram no comparativo como se tivessem diferença zero. As planilhas indicam a elegibilidade dos documentos; o PDF lista as exclusões.

Classificação OK corresponde a `MATCH_EXACT`. Achados tratados ou justificados permanecem no histórico, mas deixam a lista de prioridades abertas. As notas de entrada mostram o emitente como contraparte; as saídas mostram o destinatário.

A revisão de relatório inclui a versão do modelo. Relatórios anteriores permanecem imutáveis e baixáveis. As abas técnicas anteriores foram mantidas, ocultas, no Excel; as abas operacionais são exibidas primeiro. Não houve migração de banco nem modificação de documentos, títulos ou partidas.

## Comparação reproduzível

```bash
python -m scripts.compare_auditor_reports --original /caminho/auditorfiscal-1.2.2
```

O script usa o ZIP apenas como referência externa para gerar os relatórios originais. A aplicação distribuída continua sem PHP/Laravel, sem API adicional e sem dependência do projeto de referência.

A amostra sintética contém oito NF-e, 24 itens, quatro entradas (R$ 1.524,00), quatro saídas (R$ 2.004,00), total R$ 3.528,00, base IBS/CBS R$ 2.652,00. A comparação automatizada verifica 672 células: 48 em notas, 192 em itens/componentes, 192 em tributos e 240 em classificações. Também gera ambos os PDFs, ambos os Excel, o retrato e o resultado da comparação para revisão visual. `xlsxwriter` é necessário apenas para executar o exportador de referência; não foi adicionado ao runtime da aplicação.

O PDF integrado preserva a organização editorial do original com a identidade do Escritura e acrescenta memória, tratamento e diagnóstico. Não é uma reprodução pixel a pixel. O original consultado não oferece esses acréscimos no mesmo nível de detalhe. Evidências idênticas são agrupadas no PDF com todas as notas/itens relacionados, sem exclusão de achados.

A suíte `test_auditor_presentation.py` verifica as seções, contraparte, somatórios, colunas, tipos de célula, classificação de cobertura e prioridades. `scripts/browser_evolution.py` executa a navegação real com as mesmas oito notas, além dos fluxos interno/avulso anteriores. Artefatos do navegador incluem `auditor-painel-1440.png`, `auditor-analise-1440.png`, `auditor-grade-1440.png`, `auditor-inspecao-itens-1440.png`, `auditor-inspecao-390.png`, `auditor-relatorios-1440.png` e `auditoria-comparativa.pdf/.xlsx`.

## Limites concretos

- Amostras de validação são sintéticas; não houve homologação com base operacional do escritório.
- Não foram inventadas regras tributárias novas. Validade de catálogos e cenários especiais permanece condicionada à revisão fiscal documentada na cobertura.
- CT-e OS mantém espelho; equivalência visual com DACTE OS original continua pendente.
- Assinatura Windows e notarização macOS continuam pendentes. A publicação deve conservar os gates existentes de instalação, atualização, visualizador nativo e Docker.
- Os requisitos de fidelidade dos modelos Prosoft são separados desta comparação com os relatórios do Auditor 1.2.2.
