# Cofre A1 separado no Docker

O A1 é configurado no cadastro da empresa. O banco armazena PFX e senha cifrados
com AES-256-GCM; a chave do cofre fica fora de `/data` e dos backups do banco.
Os controles de identidade, empresa, ambientes, permissões e TLS permanecem os
mesmos. Não há login/senha do portal implementado como autenticação da API ADN.

## Instalação nova ou instalação sem A1 cadastrado

O compose.yaml principal já inclui o volume reception_vault e a configuração
interna do diretório. Para novos cadastros, bastam compose.yaml e .env existentes:

```sh
docker compose config --quiet
docker compose up -d
```

Não há override A1 para acrescentar. A mesma configuração está na raiz e nos
pacotes production/develop. O volume mantém exatamente o nome lógico
reception_vault e o destino usados anteriormente pelo override, permitindo
reutilizar a chave sem cópia ao manter COMPOSE_PROJECT_NAME. O arquivo legado
continua no repositório somente para compatibilidade, não é necessário nem
incluído nos novos pacotes. Não altere o nome do projeto durante a atualização.

A inclusão não migra uma chave de outro diretório. Antes de substituir o Compose
de instalação existente, identifique o armazenamento atual: se usava o volume
anterior no mesmo projeto, ele será reutilizado; se a chave está em outro local,
preserve o original e migre por procedimento administrativo protegido antes de
qualquer recriação. Não apague o contêiner antigo se ele for a única cópia.
Sem a chave vinculada, o aplicativo continua recusando o acesso, sem gerar outra.

O volume é isolado por projeto pelo Compose. /data e os demais serviços não
mudam; root somente leitura, UID 10001 e capabilities mínimas permanecem.
Nenhum segredo é colocado no .env, imagem, relatório ou log.

Na imagem, o diretório vazio `/run/escritura/reception-vault` pertence a
10001:10001 e tem modo 0700. Ao inicializar um volume vazio, o Docker copia os
metadados do destino da imagem. A aplicação cria a chave aleatória com modo
0600 no primeiro cadastro A1. Isso evita mudar permissões de diretórios do host.
Os arquivos não devem estar em `/tmp`, tmpfs ou no filesystem efêmero do contêiner.
Veja [volumes Docker](https://docs.docker.com/engine/storage/volumes/) e
[merge por destino de volumes no Compose](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/).

Mantenha o compose.yaml e o projeto nas recriações futuras. Remover o contêiner mantém o
volume; remover o volume perde a chave. **Não execute `down -v`**, nem remova o
volume ao atualizar. Mantenha backup protegido e separado da chave, com controle
de acesso equivalente ao do certificado. Persistência não substitui backup.

## Instalação com A1 já cadastrado ou recuperação

Não conecte um volume vazio e não recadastre o A1 para tentar corrigir perda de
chave. A base guarda o identificador UUID da chave anterior e falha fechada
quando ela falta ou diverge; uma chave nova não decifra os registros antigos.
`configured=true` só informa cadastro existente e `/api/health` não verifica
descriptação: use a conferência local A1 da empresa, sem consultar órgão fiscal.

Recupere a chave original por um canal administrativo protegido, conservando
nome UUID, bytes e permissões privadas Linux, no volume separado. Restaure o
backup cifrado `.eibk` em destino novo isolado e confira localmente todas as
empresas/ambientes antes de qualquer troca. A chave do envelope `.eibk` e a chave
do cofre A1 são segredos diferentes. Não publique cópias em GitHub/artefatos nem
as coloque junto ao backup do banco. Sem a chave original, este incremento não
implementa reset/recadastro global, rotação, escrow ou recuperação mágica.

Não há migração automática de cofre já existente. Uma chave protegida por DPAPI
CurrentUser no Windows exige seu próprio procedimento; copiar bytes para Linux
não torna essa chave portátil. Evite iniciar workers de integrações durante
ensaios de recuperação. Nenhuma operação fiscal externa é necessária para
verificar que a chave correta volta a abrir o A1.

## Provas e limites

`tests/test_reception_vault_persistence.py` testa reinício real de processo,
backup cifrado/restauração, chave correta/ausente/incorreta, rollback e isolamento
com certificados sintéticos. Esses testes não equivalem a um teste Docker.

O job separado de CI `Cofre A1 · recriação e recuperação Docker` exige daemon e
constrói a base com o runtime fixado e o estágio `reception-runtime` da própria
imagem. Cada etapa roda em contêiner novo, UID 10001, rede desativada, root
somente leitura e volumes temporários UUID. Cobre cadastro matriz/filial,
reabertura após remoção do contêiner anterior, recusa de chave ausente/incorreta,
backup cifrado do banco, cópia separada de chave, restauração em volumes novos
e nova reabertura. Remove somente os recursos de teste que criou; não usa
certificados reais, consulta fiscal ou stack existente. Não faz skip silencioso
se Docker faltar. O resultado deve ser conferido no CI da PR antes de operar.
O banco da fixture usa mount gravável, como `/data` do app: mesmo a conexão
SQLite `mode=ro` pode precisar criar arquivos auxiliares WAL/SHM. O ensaio confere
que os registros do cofre não mudam durante o backup; a chave de origem permanece
em mount somente leitura. Veja [SQLite WAL em leitura](https://sqlite.org/wal.html#read_only_databases).

Na composição com develop `7ddec58017d6506bd58d3b56563ee48b87fb1730` (dev.52),
a regressão local executou **278 testes em 113,859 s: 268 aprovados, 10 skips,
nenhuma falha/erro**. Incluiu recepção, cofre, oito casos novos de persistência/
fixture, backups, infraestrutura/ZIP de deploy, permissões/contexto, integrações,
domínio e regressões de relatórios da nova base. O teste de pacote confere os
dois ZIPs gerados e a exclusão de fontes/dados/segredos locais. Não houve mudança
de frontend, e não se repetiu build/browser local; os jobs existentes são mantidos.

Este executor local não tem Docker/Podman nem socket disponível: não se afirma
execução local desse job. Não houve deploy, restauração operacional nem
homologação junto à SEFAZ/ADN. A consulta ADN pela nova view continua pendente
da resolução documental da URL contribuinte; esta correção de armazenamento
não a anuncia como liberada.
