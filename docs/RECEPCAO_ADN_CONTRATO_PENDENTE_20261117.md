# Continuidade da recepção ADN — 17/11/2026

O contrato contribuinte GET `/DFe/{NSU}` permite receber documentos em que o
interessado seja emitente, tomador ou intermediário. O
[manual atual](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-apis-adn-sistema-nacional-nfse.pdf)
e o [manual v1.1 de 03/11/2026](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-municipios-apis-adn-sistema-nacional-nfs-e-v1-1-20261103.pdf/@@download/file)
distinguem inscrição do certificado, mesma raiz com CNPJ completo e procuração
para outra inscrição. O cadastro A1 e o cliente existentes mantêm essas distinções;
nenhuma autorização de terceiro é presumida. O suporte CPF/A3 não está implementado.

A [relação oficial de APIs](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao)
aponta as documentações de contribuintes em `/contribuintes/docs/index.html` nos
dois ambientes. Os dois MHTML fornecidos pelo usuário renderizam host raiz com
`/DFe/{NSU}`, mas ligam os downloads OpenAPI em
`https://adn.nfse.gov.br/contribuintes/swagger/v1/swagger.json` e
`https://adn.producaorestrita.nfse.gov.br/contribuintes/swagger/v1/swagger.json`.
Esses dois downloads retornaram HTTP 503 no executor em 17/11/2026; a ferramenta
web também não conseguiu abri-los. Os MHTML não contêm `servers`/basePath nem o
JSON completo que resolva essa discrepância. O manual descreve a operação
relativa e não prova, sozinho, o prefixo completo de roteamento.

O ZIP do módulo NFS-e Nacional 0.8.4 foi conferido por hash e lido estaticamente:
`ee6a4922c8559ffe1d6b76307b0b7360d5c50e0e63b5d726a8f06df9af1bac66`, 732 entradas.
`DistributionClient.php` compõe `/contribuintes/DFe/{NSU}`. Isso é evidência do
comportamento da referência de terceiros, não confirmação oficial do endpoint.
Não se executou PHP nem se copiou código/dependência desse módulo. A referência
Manifestador 1.1.1 também foi novamente conferida:
`ac08afe2c1ee9bf1b17f71d838662e1bef9a12dbd7388967bc0d1a03d4044317`, 538 entradas.
Seu fluxo de empresa/acervo continua como referência de organização, sem
transplantar manifestação ou regras de consulta NF-e para o ADN.

Por isso a consulta ADN na nova view continua indisponível. Não se alterou o
endpoint por tentativa, não houve fallback entre APIs contribuinte/município,
sondagem de `/DFe`, envio de certificado nem consulta fiscal. O perfil recuperado
`271e9577` segue sendo evidência de formato da resposta, não de homologação ou
de base URL ao vivo. Os testes sintéticos continuam cobrindo lote completo,
NSU exclusivo, matriz/filial, procuração, ambiente, reconsulta, versões e rollback.

O incremento coeso entregue agora é o armazenamento separado do cofre A1 no
Docker, explicado em [COFRE_A1_DOCKER.md](COFRE_A1_DOCKER.md): imagem preparada,
override optativo incluído no pacote de deploy, ensaio de recuperação sintético
e job Docker obrigatório. Ele trata uma dependência operacional comum a DF-e e
ADN; **não libera a consulta ADN nem conclui recepção externa**. A mudança não
altera menus, acervo, cursor, importação, escrituração, APIs/webhooks ou performance.

Para liberar a consulta ainda falta uma fonte primária que fixe os servidores/
base URL completos do contribuinte, seguida de teste do cliente nesse contrato.
Homologação externa com credencial e autorização próprias será uma etapa distinta,
que não foi executada. Não há promessa de automação, todos os modelos ou todos
os métodos de autenticação. A emissão da nota e a competência de escrituração
continuam sendo informações distintas.
