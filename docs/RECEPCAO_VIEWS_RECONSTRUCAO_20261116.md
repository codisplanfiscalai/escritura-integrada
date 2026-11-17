# Views DF-e e NFS-e Nacional — reconstrução local de 16/11/2026

> Continuação: [acervo, versões e bloqueio ADN em 17/11/2026](RECEPCAO_ACERVO_VERSOES_20261117.md). Este documento mantém a evidência histórica de 16/11; o agrupamento por identidade/versões e a composição atual estão descritos na continuação.

## Estado e origem

Esta é uma reconstrução em checkout novo, base `cd0a7ed05a2b6f336cccd4b3788b70d860fb0a24` (develop 0.9.0-dev.36), branch local `rebuild/dfe-nfse-ui-20261116`. Não é recuperação comprovada do incremento anterior. O checkout antigo `escritura-reception-ui-20261116`, o objeto `e6eb5a07283b18195f2da743dbf5a8b2206de226` e seu bundle não foram encontrados neste executor após inventário limitado de caminhos registrados, objetos dos 16 checkouts conhecidos e heads dos bundles disponíveis. Isso não prova sua inexistência em outros executores. Nada existente foi substituído. Não foram usados logs internos de sessões.

A reconstrução foi validada inicialmente em checkout isolado, sem publicação ou mudança operacional de banco. A continuação incorpora a base atual e é proposta como incremento parcial em PR draft, sem merge, release ou deploy. Não incorpora as alterações experimentais de compatibilidade A1 externas a esta base.

## Acesso e comportamento

O módulo Fiscal passa a ter dois acessos próprios no menu, **DF-e** e **NFS-e Nacional**, cada qual com sua view e controlador. Importações fiscais continua uma funcionalidade independente. As novas views mostram a empresa ativa, ambiente, NSU confirmado, caixa de documentos, filtros locais, downloads, relatório CSV e recibos. Abrir ou atualizar a view só lê o acervo local; não carrega A1 nem consulta serviço fiscal.

As referências Manifestador e NFS-e Nacional/Perfex 0.8.4 orientaram a separação do acervo, direção e parâmetros por empresa. Não foi copiado código PHP nem dependência proprietária. O período filtra o exercício de referência dos recibos locais, não cria busca fiscal por data. A competência declarada NFS-e (`dCompet`), emissão, recebimento e referência do recibo aparecem separadamente; nenhuma delas define automaticamente a data de entrada/escrituração.

Emitidas/recebidas usam a inscrição completa efetiva no XML: NF-e `emit`/`dest`; NFS-e `prest`/`toma`/`interm`. Mesma raiz não basta para classificar. Uma nota pode participar dos dois sentidos. Intermediário representa disponibilidade à inscrição, sem presumir que ela seja o tomador contábil. Dados ausentes, eventos e identidades ambíguas ficam a conferir. Os originais não são reescritos e eventos/cancelamentos recebidos não alteram escrituração automaticamente.

A caixa lista **ocorrências por recibo/NSU**, preservando proveniência. Ainda não é um índice único global de notas por chave: retransmissões em outros recibos podem aparecer novamente. O CSV exporta as ocorrências filtradas em um único snapshot de leitura, sem reagrupar versões divergentes; inclui ambiente, direções, datas, chave, NSU, recibo e hash. Paginação de 20, upload A1 de 5 MB e proteção do CSV de 100.000 linhas são limites locais de interface/recursos, não limites oficiais dos serviços. A classificação lê os XMLs existentes; não há índice persistente ou benchmark de grandes acervos neste incremento.

## Matriz efetiva

| Recurso | Local | Consulta externa pela nova view | Autenticação e limites |
| --- | --- | --- | --- |
| DF-e/NF-e modelo 55 | Acervo, originais, resumos, recibos, CSV, conferência A1 | Uma página explicitamente solicitada; produção e homologação já previstos no adaptador | A1/CNPJ, mesma raiz; aceitação externa não homologada nesta reconstrução |
| NFS-e ADN contribuinte | Acervo, XML/eventos, recibos, emitidas/recebidas/ambas, competência declarada e CSV | **Indisponível** até confirmar URLs pelo OpenAPI; produção/restrita são ambientes locais distintos | A1/CNPJ numérico no adaptador atual; mesma raiz e opção de tentativa com procuração de outra raiz não concedem autorização |
| NFC-e, CT-e, MDF-e | Nenhuma cobertura nova | Indisponível | Não extrapolar distribuição NF-e |
| CPF, A3/nuvem, login/senha de portal | Não implementados nestas views | Indisponível | O contrato oficial admite CPF/A3, mas isso não prova suporte do aplicativo; login do portal não autentica esta API |
| Automação/agendamento | Não implementados | Indisponível | Nenhum polling ou retry automático novo |

Não foram alteradas URLs do backend legado nem declaradas como recém-confirmadas. Sua API anterior permanece existente. A nova rota de consulta ADN recusa antes de credenciais, cursor e transporte. A confirmação pendente de URLs não impede menus, configuração ou leitura de documentos já recebidos. NF-e e ADN têm contratos, ambientes e critérios diferentes; esta matriz não promete todos os documentos emitidos/recebidos.

A documentação contribuinte fornecida descreve GET `/DFe/{NSU}` exclusivo, `lote` booleano padrão true, CNPJ completo ou CPF mutuamente exclusivos e `TipoConsulta`. Município (NSU inclusivo e seu lote) e POST de recepção/envio ao ADN não são contratos de download do contribuinte. Foram retiradas as esperas locais genéricas de 3600/60 segundos aplicadas ao ADN sem fundamento documentado. `Retry-After` recebido é respeitado; o lease de concorrência e a idempotência continuam internos. Não há repetição automática. Regras NF-e não foram transplantadas para ADN. Outros sistemas do mesmo ator/CNPJ precisam coordenar distNSU e intervalos oficiais; a trava desta base não coordena instalações externas.

## Empresa, permissões e A1

Cadastro da empresa → **Recepção fiscal** concentra ambientes padrão e A1 PFX/P12, inclusive atualização de ambientes sem reenviar certificado. A view usa a empresa selecionada. Configurar outra empresa no seu cadastro não muda a ativa. Utilizam-se as permissões existentes: `system.companies` read/edit para configuração; `fiscal.imports` read/import/export para leitura/consulta/download. Essa reutilização é compatibilidade de autorização, não união da funcionalidade com importações.

PFX e senha são cifrados com AES-256-GCM. AAD vincula instalação, empresa, inscrição e versão; ciphertext fica na base. A chave fica **fora da pasta de dados e dos backups normais**, em perfil privado do SO ou `ESCRITURA_RECEPTION_VAULT_DIR`. POSIX exige proprietário/permissões privados e rejeita links; Windows protege a chave com DPAPI CurrentUser, reaproveitando a fronteira existente. Não há ajuste de permissões de host neste trabalho. Administrador da instalação precisa preservar a chave separadamente; backup da base sozinho não recupera o cofre. Chave ausente/adulterada não é regenerada silenciosamente e não provoca fallback para outro certificado.

Em servidor/contêiner, o diretório da chave precisa de persistência privada separada da base. O Compose atual monta apenas `/data` e usa filesystem somente leitura: não oferece essa persistência por padrão. Antes de usar o cofre em Docker, o operador precisa configurar `ESCRITURA_RECEPTION_VAULT_DIR` e seu armazenamento persistente separado, com a identidade/permissões adequadas. Esta reconstrução não altera Compose, volumes ou permissões de host nem declara esse cenário operacionalmente validado. Menus e acervo local continuam independentes dessa configuração.

Upload exige sessão, CSRF, permissão da empresa e HTTPS (exceção somente conexão e hostname de loopback para desktop). Limite de recepção é aplicado ao stream multipart. Arquivo e senha não têm read-back; logs/auditoria recebem somente metadados permitidos. O formulário limpa segredos após tentativa e desmontagem; conflito posterior nas preferências preserva a versão A1 já salva, sem repetir upload. Mudança de A1 durante preparação impede uma consulta com material obsoleto.

A mesma validação A1 e política TLS publicada é compartilhada entre cofre e perfis locais. TLS >= 1.2, hostname e verificação de servidor permanecem obrigatórios. Não há conversão exigida ao usuário nem habilitação de algoritmo fraco no TLS. Foram testados somente containers sintéticos modernos, PBESv1/3DES e sem senha no Linux. Isso não comprova todos os PFX, RC2, curvas/chaves, cadeia ICP-Brasil, LCR, procuração, A3, CPF, Windows ou macOS. macOS Intel conserva o helper nativo já existente; ARM/Linux/Windows conservam o backend anterior. Não foram importadas as alterações A1 antigas pendentes. Remoção/revogação completa do cofre e gestão de sua recuperação ainda não têm fluxo próprio nesta interface.

## Integração com escrituração

Não há lançamento automático nem botão que contorne a revisão. O backend de revisão/importação existente continua canônico. Resumo sem XML íntegro permanece pendente e explicável. Os testes comprovam que a mesma NF-e importada por XML e depois recebida, com dados de revisão iguais, não cria outro documento e preserva o original. A regressão existente cobre reimportações concorrentes, empresa separada, divergências e bloqueio de competência fechada. O leitor de escrituração NFS-e Nacional ainda não existe; baixar NFS-e não equivale a escriturá-la. Agrupamento global de divergências no acervo é lacuna explícita.

## Evidência e reprodução

- Runtime isolado: `reception-rebuild-runtime-20261116`, dependências exatas de `docker/runtime.lock`, sem alterar pins.
- `PYTHONPATH=.:tests python -m unittest test_reception_workspace test_reception_vault test_import_revision`: 29 casos, OK, 1 skip Windows neste Linux.
- Recepção/cofre: 90 casos, OK, 9 skips de plataforma antes da extração final do relatório; os 29 casos acima revalidam as mudanças finais correspondentes.
- `cd frontend && node --test tests/*.test.js`: 205 aprovados; `npm run build`: aprovado, aviso existente de chunk >500 kB.
- `PYTHONPATH=. python scripts/browser_reception_rebuild.py`: aprovado com headless Chromium 1194 já disponível, usando `ESCRITURA_TEST_BROWSER`; menus/views separados, acervo sintético ADN, ambos papéis, CSV, A1 sintético com senha inválida/válida, chamada NF-e via stub, download, troca de empresa, sem erros JS. Imagens e report em `artifacts/browser-reception-rebuild/` são artefatos locais ignorados pelo Git. Chromium completo do sistema não iniciou por bloqueio de socket AF_UNIX; não se alterou o host.
- Suíte Python completa: **1.415 casos em 705,214 s; 1.366 aprovados, 45 skips e 4 erros**. Os quatro são `test_docker_updates.SocketBoundaryTests`: `test_current_lookup_waits_for_slow_registry_without_using_short_admission_timeout`, `test_invalid_and_oversized_socket_payload_fail_closed`, `test_real_socket_plan_and_job_round_trip`, `test_wrong_peer_uid_and_missing_socket_cannot_execute`. Todos falharam ao criar socket AF_UNIX com `PermissionError: [Errno 1] Operation not permitted`. Essa implementação e seus testes não foram alterados. Não se alterou o host, não se ignoraram esses testes e a suíte completa **não está verde** neste ambiente. Não houve outras falhas/erros nessa rodada.
- Após o ajuste final da proteção de fórmulas CSV com espaços iniciais: 7 testes de workspace aprovados. O cenário Chromium final também passou sem depender de `PYTHONPATH` e com bootstrap em base temporária.
- O cenário de navegador está registrado no workflow Linux existente para uma futura publicação autorizada, sem desativar checks. **CI remoto e pacotes Windows/macOS não foram executados** nesta reconstrução local; não há alegação de homologação fiscal.

Fontes: quatro MHTML fornecidos, lidos integralmente pela coordenação (Contribuinte produção, Contribuinte produção restrita, Município, Recepção/envio), [manual ADN contribuinte vigente](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-apis-adn-sistema-nacional-nfse.pdf), [FAQ 19.3/28.2](https://www.gov.br/nfse/pt-br/perguntas-frequentes/perguntas-frequentes-nfs-e-v1-3-20261106.pdf/@@download/file) e [NT 008/2026, mapeamento DANFSe](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/rtc/nt-008-se-cgnfse-danfse-20260505.pdf). Esta última sustenta os caminhos de identificação/datas, não validação XSD completa. Os OpenAPI contribuinte `https://adn.nfse.gov.br/contribuintes/swagger/v1/swagger.json` e equivalente de produção restrita retornaram 503 na verificação sem certificado; não foi inferido endpoint a partir de anúncios gerais.
