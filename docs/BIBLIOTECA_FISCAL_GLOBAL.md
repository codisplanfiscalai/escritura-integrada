# Tabelas e padrões fiscais globais

## Tabelas compartilhadas

Fiscal → CFOP e associações contém o painel **Tabelas fiscais globais**. Parâmetros → Cadastros fiscais também abre esse painel, inicialmente na tabela de serviços.

- A instalação disponibiliza 619 códigos CFOP da referência CONFAZ já incorporada ao projeto. As redações oficiais e suas vigências são preservadas separadamente da descrição informativa editável.
- Quando há correspondência exata de código com a carga `tabcfop` fornecida, a tabela apresenta as alíquotas e os indicadores declarados nessa origem. Não converte códigos legados ou sem correspondência.
- A origem não informou vigência nem os critérios tributários de cada alíquota. Esses números **não representam uma alíquota única do CFOP**. Não identificam automaticamente tributo, UF, produto, regime, base, crédito ou incidência.
- Administradores podem alterar descrição, fonte, vigência declarada, situação e lista de alíquotas informativas. Motivo, controle de versão, histórico e auditoria são obrigatórios. As alíquotas originais permanecem disponíveis.
- Serviços globais são cadastrados explicitamente, identificados por tabela (`lc116`, `national_nfse` ou `municipal`), jurisdição (`BR` ou código IBGE municipal) e código. O mesmo código em tabelas/jurisdições diferentes representa registros distintos. A aplicação não semeia uma lista municipal ou nacional incompleta como se fosse oficial.

As tabelas globais não substituem os catálogos ou os cadastros de produtos/serviços das empresas. A migração não promove dados privados das empresas à biblioteca compartilhada. Não há alteração do importador ou da pré-apuração para consultar essas alíquotas.

## Biblioteca de padrões

Parâmetros → Regras e vigência/Modelos contém **Biblioteca global de padrões fiscais**.

1. O administrador publica um padrão com código, nome, fonte, regime, segmento e vigência declarada opcional.
2. As estruturas iniciais cobrem os quatro regimes cadastrais e os segmentos comércio, indústria e serviços. São estruturas de trabalho sem alíquotas ou validação legal. Não afirmam incidência de todos os tributos enumerados nem substituem a análise de Simples Nacional, monofásico, substituição, benefícios ou operações especiais.
3. **Derivar global** copia um padrão publicado para um novo padrão com `base_pattern_id` e `base_version`. A origem e a versão exata ficam registradas como linhagem imutável, inclusive quando a origem muda depois. Edite a cópia sem alterar o padrão de origem.
4. Cada regra proposta pode informar tributo, alíquota, sentido, CFOP, NCM, UF, município e fundamento específico. Somente esses campos são publicados: IDs, documentos ou snapshots de uma empresa não são copiados para padrões.
5. Para importar, o operador confirma segmento, período e responsável. O regime deve coincidir com a empresa e o intervalo deve respeitar a vigência global, quando preenchida. Segmento e atividade são declarações confirmadas para selecionar a estrutura. Uma especialização como **Farmácia** pode manter o segmento Comércio e declarar sua atividade, sem presumir monofásico, substituição, benefício ou alíquota. O padrão pode exigir também um prefixo CNAE de dois a sete dígitos: nesse caso o servidor confere o CNAE principal cadastrado da empresa e bloqueia a importação incompatível ou sem CNAE. Sem esse filtro, a atividade permanece uma declaração manual e não constitui enquadramento legal.
6. A prévia mostra o padrão e sua versão, as regras propostas e os registros existentes que serão preservados. A confirmação confere novamente empresa, permissões, versão e hash dentro da transação.
7. A aplicação cria regras **em rascunho e inativas**, preservando as regras existentes. O operador ajusta as cópias em Regras e vigência e deve selecionar o filtro **Inativas** para encontrá-las antes da revisão/ativação.

A mesma combinação empresa/padrão/versão/vigência/segmento é idempotente após uma nova prévia válida; uma confirmação com hash antigo é recusada mesmo se aquela combinação já foi aplicada. Uma nova versão global pode ser importada separadamente e não substitui as cópias anteriores. Não existe sincronização automática entre a biblioteca e a empresa. O vínculo de origem registra versão, segmento e atividade confirmados, filtro CNAE, período, motivo, responsável e IDs iniciais das regras. O histórico normal de regras preserva suas edições posteriores.

O filtro CNAE bloqueia apenas a **importação do padrão**. Os metadados ficam no snapshot empresarial, associado aos IDs iniciais das regras; não são condições executáveis das cópias na pré-apuração. O painel **Cópias nesta empresa e condições de origem** identifica a origem e avisa sobre mudanças/incompatibilidades de CNAE ou regime atuais. Esses avisos não desativam regras nem alteram cálculos. Alterações de atividade ou cadastro exigem revisão fiscal das cópias antes de usá-las novamente.

Publicar ou importar um padrão não calcula tributos, não concede créditos, não finaliza apuração e não escreve documentos. A pré-apuração existente continua exigindo seleção explícita de bases e regras conferidas, ativas e compatíveis.

## Persistência e segurança

Os módulos de migração são aditivos. A integração da alteração usa a mesma versão de esquema 6 dos demais cadastros globais; `Database` deve chamar todas as migrações antes de gravar essa marca, com backup da versão anterior. Nenhum banco operacional foi alterado para desenvolver ou testar esta funcionalidade.

As extrações integrais TXT/PDF já incorporadas ao projeto, seus metadados e hashes, os catálogos, as versões dos padrões e os snapshots de importação integram o backup SQLite. Os metadados preservam que os bytes dos anexos originais e os pixels do PDF não foram certificados; esta alteração não os trata como novas provas de conferência. O manifesto valida também os hashes dessas tabelas e recusa uma fonte cujo conteúdo diverge do hash armazenado. A restauração permanece em pasta nova.

Rotas são contextualizadas em `/api/companies/{cid}`. Leitura exige `fiscal.masters` ou `fiscal.parameters` na empresa. Alterações globais exigem administrador, mesmo que o usuário possua permissão de edição local. Importação exige criação de parâmetros na empresa e não concede acesso a outras empresas.

## Contrato resumido da API

- `GET/POST /global-fiscal-catalogs`, `PUT /global-fiscal-catalogs/{id}`, `GET /global-fiscal-catalogs/{id}/versions`.
- `GET/POST /fiscal-patterns`, `PUT /fiscal-patterns/{id}`, `GET /fiscal-patterns/{id}/versions`.
- `POST /fiscal-patterns/{id}/preview`: versão, segmento, atividade confirmada quando exigida, início e fim da vigência, motivo e responsável. Retorna `preview_hash`.
- `POST /fiscal-patterns/{id}/apply`: dados da prévia, `preview_hash`, motivo e responsável. Retorna IDs e indicador de duplicidade.
- `GET /fiscal-patterns/imports`: origens e snapshots exclusivos da empresa consultada.

## Verificação

`tests/test_fiscal_library.py` cobre referência/valores originais, serviços em jurisdições diferentes, concorrência, derivação/linhagem, atividade e filtro CNAE, confirmação de duplicidade com prévia vigente, lista permitida de campos, autorização global versus local, preservação entre empresas, prévia desatualizada, importação inativa/idempotente, adaptação independente e backup/restauração.

`scripts/browser_fiscal_library.py` executa os fluxos reais em Chromium com base demonstrativa temporária. O gate da integração deve repetir a suíte Python, os testes frontend, o build e esse smoke após resolver os pontos compartilhados da migração.
