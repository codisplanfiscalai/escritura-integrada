# Consulta e download por NSU

As telas **DF-e** e **NFS-e Nacional** consultam serviços independentes, com
ambiente, inscrição completa, cursor e histórico próprios. Os endereços oficiais
são internos; não há exigência de confirmação de URL pelo usuário.

## Fluxo

1. Cadastrar A1 e ambientes em Empresas → Recepção fiscal.
2. Na tela do serviço, usar **Consultar e baixar documentos**.
3. Cada lote é validado e salvo com seu retorno original. Só então o NSU persistido
   é atualizado. Quantidade de documentos não é usada como NSU.
4. A tela continua enquanto houver progresso e a API permitir, sem teto total de
   documentos por consulta. É possível parar após o lote atual e retomar depois.
5. Mudança de empresa, contexto, configuração, erro, falta de progresso ou espera
   encerra a sequência; uma tentativa de resultado incerto não é repetida automaticamente.

O fechamento da tela interrompe novos lotes, mas não desfaz um lote já enviado.
Reabertura apenas lê o acervo; não consulta o Fisco sem nova ação do usuário.

## Contratos separados

- **NF-e:** `distNSU`, `ultNSU`/`maxNSU`. Não se aplica espera fixa entre lotes
  positivos ainda não esgotados. Os retornos 137/656 ou `ultNSU == maxNSU`
  preservam a espera de uma hora prevista pelo serviço.
- Na rejeição 656, `ultNSU` maior e válido fornecido pela SEFAZ sincroniza o cursor,
  após salvar o retorno. O recibo avisa que isso **não comprova download dos XMLs
  intermediários**, que podem ter sido obtidos por outro sistema. Valor ausente,
  inválido ou inferior nunca é usado para avançar ou regredir silenciosamente.
- **NFS-e ADN:** GET `/DFe/{NSU}?lote=true`, sequência exclusiva de int64. O próximo
  NSU é o maior NSU validado do lote. A API não oferece `maxNSU` nesse contrato;
  lote não vazio permite a consulta seguinte, não prova que haverá mais documentos.
- `NENHUM_DOCUMENTO_LOCALIZADO`/E2220 encerram a coleta. HTTP 404 sem resposta
  fiscal reconhecida não significa ausência de documentos. `Retry-After` é respeitado.
- NSU numérico ou string decimal é tratado sem conversão para float. Campos
  adicionais e alertas não contraditórios não bloqueiam os XMLs. Data de geração
  inválida no envelope é recuperada do XML validado quando possível, ou fica ausente como metadado, sem inventar data contábil.

TLS, identidade, permissões, isolamento de empresas, limites de proteção contra
arquivos corrompidos/descompressão abusiva e persistência atômica permanecem.
Esses controles não são limites de volume de documentos do usuário.
Receber/baixar não emite, manifesta, cancela nem escritura documentos.

## Referências e validação

- Portal oficial de APIs NFS-e: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao
- Produção: https://adn.nfse.gov.br/contribuintes/docs/index.html
- Produção restrita: https://adn.producaorestrita.nfse.gov.br/contribuintes/docs/index.html
- NT 2014.002, retorno ultNSU na rejeição 656 (v1.14): https://www.nfe.fazenda.gov.br/Portal/exibirArquivo.aspx?conteudo=VgPuhtPApQo%3D
- MOC NF-e, distribuição e intervalos: https://moc.sped.fazenda.pr.gov.br/NFe_NFCe/NFe_NFCe/NFeDistribuicaoDFe.html

O contrato de contribuinte e os fluxos dos códigos-fonte fornecidos foram
comparados com a implementação. Testes usam XMLs, A1 e transportes sintéticos.
Não representam uma consulta real homologada com certificado do cliente.

Esta descrição substitui o bloqueio de URL/consulta única descrito nos relatórios
históricos da reconstrução de recepção. O cofre Docker permanece no Compose
principal; não são adicionados scripts ou arquivos de configuração ao deployment.
