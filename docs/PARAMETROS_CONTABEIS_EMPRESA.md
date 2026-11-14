# Parâmetros contábeis por empresa

Em **Empresas → Editar → Contábil**, a empresa editada pode escolher qualquer
versão publicada da biblioteca global (por exemplo, o plano 050) sem trocar a
empresa ativa do escritório.

- **Global compartilhado:** grava apenas o vínculo; não duplica a definição.
- **Plano próprio:** duplica explicitamente o plano inteiro ou somente contas
  usadas e pais necessários. Contas, identificadores e lançamentos anteriores
  não são apagados nem remapeados automaticamente.
- O serviço já existente faz a prévia e a confirmação. Divergências de contas
  usadas ou de propriedades continuam identificadas; não se convertem saldos
  entre planos silenciosamente.
- Histórico e centro de custo padrão são sugestões editáveis para novos
  lançamentos manuais. Não reescrevem lançamentos, importações ou documentos.
  Cada parte é salva separadamente do cadastro geral da empresa.
- O centro escolhido precisa estar ativo e pertencer à empresa. Se for
  desativado depois, deixa de ser sugerido, sem apagar a configuração histórica.

## Permissões e persistência

Consulta e edição usam as permissões centrais de plano de contas. A adoção
exige inclusão; duplicação do vínculo exige edição; centro de custo exige
consulta à rotina correspondente. CSRF, controle de versão e auditoria se
mantêm. A exceção de contexto aplica-se somente às rotas administrativas novas,
nunca aos lançamentos de empresa inativa.

Os padrões ficam na tabela `meta` existente sob chave específica da empresa,
com versão e auditoria. Não há alteração de esquema ou dependência do Atlas.
A biblioteca e o vínculo usam integralmente os serviços de domínio existentes.

## Limites da entrega

É um conjunto inicial de parâmetros contábeis funcionais, não a parametrização
completa de ECD/ECF, encerramento, assinaturas ou regras contábeis automáticas.
Não cria/publica um plano inexistente nem aplica por inferência o 050 a todas as
empresas. Novas empresas precisam ser salvas antes de selecionar um global.

Verificação local: testes HTTP/domínio e componentes Vue, build e checagem de
diff. PostgreSQL real, binários e inspeção visual em navegador precisam de
homologação no ambiente disponível. Nada foi implantado ou publicado.
