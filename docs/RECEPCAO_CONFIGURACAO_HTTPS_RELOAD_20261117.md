# Configuração única de recepção, HTTPS por proxy e reload

## Comportamento

DF-e e NFS-e Nacional continuam em menus e views separados, independentes da
escrituração. Ambiente, certificado A1 e política de procuração pertencem ao
cadastro de cada empresa. As views exibem o ambiente cadastrado como informação,
sem seletor de ambiente, arquivo ou senha. Abrir, reabrir, atualizar ou recarregar
uma view lê somente configuração pública, acervo e estado locais.

A primeira leitura não solicita ambiente do navegador: a API resolve o cadastro
no mesmo snapshot do acervo/cursor. Cada serviço recebe uma revisão opaca ligada
à empresa, inscrição, UF, preferências e versão do A1. A consulta explícita usa
essa revisão; o ambiente enviado deve coincidir com o persistido. Alterações
concorrentes antes da reserva transacional impedem o envio. A reserva fixa o
contexto daquela tentativa; alterações posteriores valem para a próxima, sem
mudar empresa, ambiente ou credencial de uma operação já reservada.

Conferir o A1 continua uma ação local explícita. Uma conferência preparada com
configuração antiga não se torna pronta numa tela atualizada. A consulta externa
continua exigindo clique; salvar cadastro ou recarregar não a executa. A API
legada de conferência local aceita `environment` somente se igual ao cadastrado,
com verificação da revisão antes/depois da leitura A1. A API legada de recepção
em Importações mantém seu contrato existente.

Trocar empresa, exercício, módulo, usuário ou permissões invalida leituras,
recibos, versões, conferência e intenção da tela. Respostas tardias não ocupam a
empresa nova. A troca de empresa também limpa a revisão da configuração. O cofre
continua cifrado por empresa, sem leitura de certificado ou senha pela API.

Um retry explícito com a mesma identificação recupera o recibo original, mesmo
se o cadastro mudou: não envia novamente nem redireciona a tentativa para outro
ambiente. Conflito comprovado antes do envio atualiza somente metadados locais e
exige novo clique. Resultados incertos continuam sem repetição automática.
Receber, baixar ou listar documentos não escritura e não manifesta documentos.

## Diagnóstico do upload A1 e HTTPS

O erro observado `Use HTTPS para configurar o A1.` ocorre antes da leitura do
PFX: o aplicativo viu uma requisição HTTP não enquadrada na exceção desktop de
loopback. Isso não diagnostica senha, algoritmo ou incompatibilidade do A1. O
endereço do navegador sem esquema visível também não comprova onde o TLS termina.

Quando o TLS termina num proxy reverso, o Uvicorn deve confiar explicitamente no
IP/CIDR desse proxy para interpretar `X-Forwarded-Proto`. A entrada do container
agora valida `FORWARDED_ALLOW_IPS` e os três templates Compose repassam a variável.
O padrão permanece `127.0.0.1`. Use somente endereços reais do proxy **vistos pelo
container**, limitando o acesso à porta da aplicação e fazendo o proxy substituir
os cabeçalhos encaminhados recebidos do cliente. Não use uma faixa inteira de
clientes como proxy. Curinga, rede global e nomes não resolvidos são recusados na
inicialização. `ESCRITURA_COOKIE_SECURE` não substitui essa identificação do proxy.

A documentação oficial explica a terminação TLS e a confiança nos cabeçalhos:
[FastAPI: Behind a Proxy](https://fastapi.tiangolo.com/advanced/behind-a-proxy/).
A correção não inventa o IP do proxy instalado, não instala TLS e não altera a
produção. É necessário confirmar no ambiente do operador o TLS externo, o salto
até o app e o endereço autorizado; sem isso o upload HTTP continua recusado.

Um seletor de certificado **do navegador** disparado no reload pode pertencer ao
handshake TLS do site/proxy. É distinto de enviar um PFX ao backend e da conexão
mTLS de saída para um órgão fiscal. O código da aplicação e os testes de abertura
não solicitam certificado ao navegador. O teste Chromium usa servidor local sem
proxy TLS: não reproduz nem exclui uma configuração de autenticação de cliente no
proxy do operador. Não foi acessado o site real para investigar seu handshake.

## Matriz local de formatos

Executor Linux, Python 3.12, cryptography 50.0.0 (OpenSSL próprio 4.0.1), SSL do
Python OpenSSL 3.5.8; gerador CLI RC2 OpenSSL 3.5.7. Somente identidades sintéticas.

| Chave / assinatura do certificado | Proteção do PKCS#12 | Evidência nesta árvore |
| --- | --- | --- |
| RSA 2048 / RSA-SHA256, cadeia sintética | PBES2 SHA256 + AES256-CBC | Leitura e contexto TLS local aprovados; senha incorreta recusada |
| RSA 3072 / RSA-SHA256, cadeia sintética | PBES2 SHA256 + AES256-CBC | Idem |
| EC P-256 / RSA-SHA256, cadeia sintética | PBES2 SHA256 + AES256-CBC | Idem; chave EC não significa assinatura ECDSA neste caso |
| As mesmas três chaves/cadeias | PBES1 SHA1 + 3DES; sem proteção do container | Seis combinações adicionais aprovadas; senha incorreta recusada nos containers protegidos |
| RSA 2048 / RSA-SHA256 | RC2-40-CBC no container, chave protegida com 3DES | Fixture OpenSSL `-legacy` lida; senha incorreta recusada; sem ativar cifra legada no TLS |

Os testes não exigem conversão/exportação do certificado pelo usuário. Proteção
legada do arquivo não autoriza TLS legado: hostname e certificado do servidor
continuam obrigatórios, mínimo TLS 1.2. A cadeia foi carregada; isso não é
validação da cadeia ICP-Brasil ou handshake com um serviço externo. Não se
promete todo PKCS#12, toda assinatura, A3, CPF ou autenticação por senha de portal.
Os novos casos não foram executados fisicamente em Windows/macOS Intel/ARM neste
executor. O caminho nativo Intel existente e seus testes de CI foram preservados.

## Limites e verificação

- A consulta externa ADN desta view continua pendente de confirmar URLs no
  contrato OpenAPI; não foi habilitada a partir de login do portal ou referências.
- A correção do cofre persistente em Docker é a frente independente PR78; o erro
  HTTPS pode impedir o upload antes de chegar a esse cofre. Nenhuma mudança do
  armazenamento dessa frente é duplicada aqui.
- Não houve operação fiscal externa, certificado real, emissão, cancelamento,
  manifestação, alteração de produção ou escrituração automática.
- Testes: `test_reception_company_configuration.py`,
  `test_reception_proxy_https.py`, `test_reception_a1_formats.py`, regressões
  `test_reception*.py`, infraestrutura/contexto/permissões, suíte frontend,
  build e `scripts/browser_reception_rebuild.py`.
- O teste de proxy cobre o middleware Uvicorn real, HTTPS nativo no ASGI, proxy
  confiável e cabeçalhos forjados; um listener HTTP local real recusa HTTPS
  forjado. Não é teste de terminação TLS no proxy de produção.
- O navegador verifica reload sem requests fiscais/check/upload, ambos ambientes
  de cadastro Produção, views sem seletor duplicado, A1 sintético correto/incorreto,
  acervo/versões/CSV, consulta NF-e por stub, troca de empresa e layout móvel.

As capturas fornecidas foram materializadas e inspecionadas somente no executor;
não integram a árvore Git, relatórios públicos ou fixtures.

## Composição revalidada com dev.53

Base develop `342b1814826c020400b1173a9f032ec70951e3b1`, com a persistência
separada do cofre e o job Docker da PR78 preservados. A integração local foi feita
por merge, sem conflito e sem alterar a frente SPED da PR79.

Nesta composição, a regressão Python executou **272 testes em 138,328 s: 262
aprovados, 10 skips, nenhuma falha ou erro**. Incluiu recepção, configuração por
empresa, proxy, formatos A1, cofre/persistência, backup/recuperação, infraestrutura,
contexto/permissões, domínio, composição Prosoft e relatórios fiscais. A suíte
frontend passou **227 testes**, o build Vite passou e o Chromium passou os cinco
cenários do roteiro de recepção, sem erro de console. Foram conferidos os três
templates Compose em JSON, `git diff --check` e a sintaxe de 381 arquivos Python/
spec, sem compilar artefatos para publicação.

Os 23 caminhos do incremento contêm somente código, testes sintéticos,
configuração pública e esta documentação. Capturas, PFX, chaves, backups e logs
locais não integram o commit. Não há Docker/Podman nem sockets disponíveis neste
executor: a recriação física de contêiner desta composição depende do job
específico do CI. Windows e macOS não foram executados fisicamente aqui.
Continuam pendentes a configuração real do proxy pelo operador e a confirmação
da URL ADN; não houve consulta fiscal externa ou implantação.
