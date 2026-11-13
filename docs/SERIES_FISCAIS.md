# Séries fiscais por empresa

O parâmetro de dígitos mínimos começa em 3 e admite inteiros de 1 a 20. O preenchimento ocorre somente em séries numéricas ASCII. Não trunca séries maiores, não substitui letras, não inventa série para campos vazios e preserva a declaração de origem em `declared_series`. XMLs e evidências originais não são reescritos.

Salvar o parâmetro não migra os registros existentes. A consulta apresenta o mínimo configurado; documentos novos e edições futuras usam a normalização. Identidades numéricas equivalentes (1, 01, 001) não geram documentos duplicados, mesmo em registros legados. Havendo conflito entre vários registros equivalentes, a operação é bloqueada sem mesclá-los.

A configuração exige permissão de edição fiscal e controle de versão. Formatos externos podem ter limites menores que o parâmetro: a exportação deve bloquear tamanho incompatível, jamais truncar.

## Validação incremental

Testes sintéticos cobrem padrões, preservação, empresa/versão, colisões e orçamento de consultas. O gate agregado da integração e a aceitação de navegador são evidências separadas. Esta reconstrução não reutiliza os resultados de execução do código perdido.

## Correção explícita de existentes

Em Parametrizações fiscais, abra “Configurar série e corrigir existentes”. Salvar o parâmetro, gerar a prévia e confirmar o lote são ações distintas. A prévia cobre todos os exercícios da empresa, mostra preservados e bloqueios e expira em 15 minutos. Alterações concorrentes no parâmetro, documentos ou permissões invalidam a confirmação. A operação é atômica, auditada e idempotente; incrementa versões para invalidar memórias/exportações pendentes. Não gera partidas, títulos ou impostos. Não reabre competências protegidas e não altera apurações finalizadas.
