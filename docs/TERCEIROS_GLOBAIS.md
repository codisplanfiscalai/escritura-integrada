# Terceiros globais com vínculos por empresa

## Limites de compartilhamento

O índice global guarda **somente identidade fiscal**:

- Pessoa: CPF completo, separado de pessoas jurídicas.
- Pessoa jurídica: raiz do CNPJ, preservando letras no CNPJ alfanumérico.
- Estabelecimento: CNPJ completo, vinculado à pessoa jurídica.

Nomes, contatos, funções de cliente/fornecedor/transportador, inscrições estaduais, notas, condições comerciais, parâmetros fiscais e financeiros continuam nos cadastros **locais de cada empresa**. Compartilhar a raiz ou o CPF/CNPJ não concede acesso nem enumera empresas, filiais, funções ou relações de terceiros.

O `masters.id` existente continua sendo a identidade operacional local. Documentos, itens e títulos não passam a referenciar IDs globais. Um participante local pode ter várias funções, sem criar um novo participante para cada função.

## Persistência e migração

- `third_parties`: identidade mínima de pessoa/organização.
- `third_party_establishments`: identidade por CNPJ completo.
- `third_party_company_links`: associação entre empresa, `masters.id` e identidade global. FKs compostas impedem vínculo a um master de outra empresa.
- `third_party_history`: snapshots e alterações apenas do cadastro local, incluindo vínculo inicial, revisões e substituições.
- `third_party_replacements`: substituição auditada de identidade incorreta por cadastro local correto.
- As IEs continuam em `masters.data_json.profile.state_registrations`, com uma linha por UF/número/situação, atividade booleana ou nula e origem/data declaradas. Não se deduz situação da existência do número; ausência não vira isenção. A IE principal antiga permanece preservada.

`migration_third_parties.migrate_third_parties` é aditiva, transacional e idempotente. Não altera `masters`, documentos, títulos nem seus IDs. Registra `third_parties_schema_version=1`. Identidades legadas inválidas ou ausentes ficam locais e não são convertidas em identidades fictícias.

Integração com o conjunto schema 6: o backup da base schema 5 deve ocorrer antes de qualquer migração, por `maintenance.backup_before_schema`; chamar esta migração antes da etapa final que grava `schema_version=6`. Não publicar apenas o hook de banco sem a atualização coordenada de `maintenance.SCHEMA_VERSION`. Um teste faz backup/restauração SQLite com vínculos/histórico, confere FKs e compara os masters antes/depois.

## Hooks de integração

1. `db.py`: chamar `migrate_third_parties(conn)` depois das migrações antigas, antes de finalizar schema 6.
2. `business.py`: incluir `ThirdPartiesMixin` no `BusinessCore`.
3. `api.py`: registrar `register_third_party_routes`.
4. `permissions.py`: mapear `third-parties` para `fiscal.masters`; `master-movements` para `fiscal.documents`.
5. `cadastros.py`: executar `sync_third_party(conn, cid, master_id, actor, reason)` **na mesma transação**, somente após criação/edição cadastral autorizada. Inclui participantes importados e funções locais acrescentadas por importação. O hook não concede permissões, não copia dados de outras empresas e não altera o master.

Nenhum parser XML ou fiscal foi alterado. A origem importada não substitui o cadastro já revisado, incluindo suas IEs. Se o fluxo de importação for movido para outro módulo, conservar os mesmos hooks após autorização e antes do commit.

## API e permissões

Todas as rotas são relativas a `/api/companies/{cid}`. Sessão, contexto ativo, CSRF e revalidação transacional são os existentes.

| Rota | Método | Permissão |
| --- | --- | --- |
| `/third-parties` | GET | `fiscal.masters/read` |
| `/third-parties/{master_id}` | GET | `fiscal.masters/read` |
| `/third-parties/{master_id}/history` | GET | `fiscal.masters/read` |
| `/third-parties/{master_id}/registrations` | PUT | `fiscal.masters/edit` |
| `/third-parties/{master_id}/reuse-preview` | POST | `fiscal.masters/read` na origem e destino |
| `/third-parties/{master_id}/reuse-confirm` | POST | leitura origem e destino + edição destino |
| `/third-parties/{master_id}/identity-correction` | POST | `fiscal.masters/edit` no destino |
| `/master-movements/{master_id}` | GET | `fiscal.documents/read` + `fiscal.masters/read` |

A API não fornece busca global de CPF/CNPJ, IDs globais, contagem de vínculos ou lista de empresas que usam a mesma identidade. Uma empresa só vê os seus cadastros. O mesmo bloqueio existe na leitura do histórico e dos movimentos.

### Revisão das inscrições estaduais

Enviar `version`, `reason` e `state_registrations`. Cada inscrição aceita `state`, `number`, `status`, `active`, `source`, `updated_at`. `status` vazio e `active: null` significam informação ausente. Número vazio exige declaração explícita `exempt`, `not_applicable` ou `not_found`. Uma revisão incrementa a versão local e preserva as inscrições anteriores no histórico.

### Reutilização cadastral explícita

O cadastro de destino já deve existir. O cadastro de origem só pode ser consultado se o mesmo usuário tiver leitura na empresa de origem. Selecionar a mesma raiz não basta: os dois cadastros precisam ter o mesmo CPF ou CNPJ **completo**.

A prévia recebe `source_company_id`, `source_master_id`, `fields`. Campos permitidos:

`name`, `trade_name`, `address`, `number`, `district`, `city`, `state`, `postal_code`, `ibge`, `im`, `cnae`, `state_registrations`.

Não se copiam contatos, funções, notas, valores, títulos, documentos, parâmetros tributários nem condições de pagamento. A prévia retorna somente os valores selecionados, versões de origem/destino e `preview_hash`. A confirmação recebe os mesmos dados e motivo obrigatório, revalida ambas as permissões e versões e altera apenas os campos escolhidos. Outra edição, alteração dos campos ou revogação da leitura de origem invalida a confirmação. Nenhuma alteração se propaga automaticamente.

O histórico do destino registra os seus valores anteriores/novos, sem revelar ID/nome da empresa de origem a usuários que só veem o destino.

### Correção de CPF/CNPJ

CPF/CNPJ de um master não é reescrito. Criar um cadastro local com a identidade correta e selecionar esse registro em `identity-correction`, com `replacement_master_id`, `version` e motivo obrigatório. O cadastro anterior é inativado e recebe sucessor no histórico. Seus documentos, títulos e snapshots fiscais antigos permanecem intactos. O novo cadastro será usado nas próximas operações. Não se reativa silenciosamente um registro já substituído.

Movimentos que já tinham o vínculo continuam podendo ser revisados, escriturados, revertidos e renegociados, inclusive com geração de títulos pelo documento original. A exceção vale somente para masters com substituição auditada e para o mesmo vínculo comprovado no documento/título persistido. Os nomes históricos vêm desses movimentos, não de uma edição cadastral posterior.

Essa origem é passada por argumentos internos, separados do payload HTTP, e é relida na transação. Informar um ID de documento/título ou uma suposta flag histórica na criação pública não autoriza selecionar o cadastro inativo. Inativos comuns, vínculos novos e reinclusão de vínculo removido continuam bloqueados. Permissões, competências, versões e validação da origem XML permanecem obrigatórias. Um XML novo do cadastro substituído conserva sua origem e um aviso sem vincular automaticamente o master inativo; reimportar a nota já existente conserva o vínculo e a idempotência.


## Produtos, serviços e rastreabilidade

Produtos e serviços continuam sendo cadastros diferentes e locais por empresa, sem entrada no índice global. `/master-movements/{master_id}` retorna os documentos locais que referenciam o item, sua posição e o snapshot do item de origem, incluindo quantidade, descrição, unidade e demais campos existentes. IDs de documentos e `source_hash` permitem rastrear o movimento em relatórios futuros. A consulta não importa nem cria movimentos adicionais.

## Interface

Em Cadastros auxiliares, o botão **Identidade e histórico** aparece em participantes e estabelecimentos. O painel separa identidade mínima de dados privados, permite revisar múltiplas IEs e oferece reutilização com seleção de origem, campos e prévia. O destino fica fixo na empresa aberta. Alterações de IEs não salvas precisam ser salvas ou descartadas antes da reutilização; o fechamento pede confirmação de descarte e a interface bloqueia duplo envio.

A lista de empresas de origem vem somente das empresas acessíveis ao usuário. Ao escolher uma origem, a API ainda exige leitura cadastral nessa empresa. Uma troca forçada de empresa, competência ou módulo invalida o painel e respostas pendentes. A seção recolhida de correção carrega explicitamente os cadastros locais elegíveis, exige selecionar o sucessor, informar motivo e confirmar os efeitos antes de registrar a substituição. A consulta de movimentos de produtos/serviços está disponível na API para os relatórios futuros.

## Validação

`tests/test_third_parties.py` cobre compartilhamento de identidade sem dados cruzados, filiais alfanuméricas/CPF, permissões origem/destino e revogação, versões e campos alterados, múltiplas IEs, correção preservando IDs e snapshots, concorrência, atomicidade, migração repetida, backup/restauração, cadastros sem identificação, produtos/serviços separados e importação sem sobrescrever dados revisados ou contornar permissões.

`tests/test_third_party_history.py` cobre o ciclo fiscal/financeiro após substituição, incluindo estorno e nova escrituração, edição em lote, reprocessamento da cobrança original, bloqueio de IDs/flags forjados, preservação do bloqueio de inativos comuns e rollback por permissões ou períodos fechados.
