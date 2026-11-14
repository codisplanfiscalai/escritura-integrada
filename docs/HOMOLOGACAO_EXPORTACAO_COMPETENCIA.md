# Homologação sintética: exportação pesquisada por competência

Base: develop `92e0809342b749abc2421b035bf7e3266194250c`.

Dois cenários acrescentados sem alterar a aplicação:
- Nota emitida em outubro e escriturada em novembro aparece na exportação de novembro, não outubro. Exportar repetidamente não muda documento, títulos ou lançamentos.
- Mês, direção e estado inválidos são rejeitados. Filtros fiscais não podem ser usados na exportação contábil.

Comando: `PYTHONPATH=tests:. python -m unittest test_movement_exports test_export_performance -q`

Resultado: 9 testes aprovados. A suíte preexistente também verifica exportação acima de 1.000 registros, texto de fórmula como texto, pesquisa acentuada, permissões e isolamento por contexto.

Limites: SQLite sintético; não é homologação Prosoft, DIX, PostgreSQL ou navegador. Não exporta SPED nem comprova existência de módulo Gerador SPED. Nenhuma mudança de produção, publicação, merge ou release.
