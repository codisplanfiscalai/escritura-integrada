# Diagnóstico da recepção NF-e e NFS-e — 18/11/2026

## Evidência observada

Inspeção autenticada na instalação do Escritura em produção, versão **0.9.0-dev.61**. A conferência local do A1 passou. Os retornos foram obtidos pelo download de originais dos próprios recibos; nenhum certificado, senha, XML fiscal ou identificador empresarial real integra esta alteração.

| Serviço | Retorno observado | Consequência |
| --- | --- | --- |
| NF-e distribuição | Envelope SOAP válido, `cStat=404`, `xMotivo=Rejeicao: Uso de prefixo de namespace nao permitido` | A SEFAZ rejeitou a requisição; não comprova ausência de documentos. |
| NFS-e ADN | `StatusProcessamento=REJEICAO`, `TipoConsulta=InscricaoCertificado`, `LoteDFe=[]`, `Erros=[]`, `Alertas=[]`, ambiente de produção | Recusa sem motivo detalhado; não comprova autorização nem ausência de documentos. |

O NSU permaneceu zero nos dois serviços, coerentemente com consultas recusadas. A interface mostrava um retorno analisado e zero documentos, mas deixava a situação da recusa somente no histórico e omitia o `cStat`.

## Correções pontuais

1. **NF-e:** o `ElementTree` serializava `distDFeInt` e seus filhos como `ns2:...`. O construtor agora declara namespaces padrão por nível, conservando os URIs SOAP/WSDL/NF-e e a estrutura `distNSU`. Não modifica o registro global de namespaces, compartilhado entre threads. O helper Apple já usava namespace padrão na área de dados NF-e.
2. **ADN:** o construtor omitia `cnpjConsulta` quando empresa e titular do certificado eram iguais. Passa a enviar explicitamente o CNPJ completo da empresa canônica também nesse caso, assim como o módulo nacional que já realizou a coleta. O helper Apple recebe a mesma correção. A política local de mesma raiz e procuração permanece obrigatória. Com parâmetro explícito da mesma raiz, o perfil esperado é `CnpjBase`; o serviço usa o perfil da requisição, preservando a verificação estrita do retorno.
3. **Recusa ADN sem códigos:** é classificada como `rejected` / `ADN_REJECTION_WITHOUT_DETAILS`, mantendo os bytes originais e o cursor. Nunca vira sucesso ou fim do histórico. Eventual `Retry-After` é respeitado.
4. **Interface:** o resultado aparece junto aos botões de consulta, com HTTP e `cStat` quando disponíveis e mensagens fixas para as falhas observadas. Texto arbitrário do serviço não é apresentado como diagnóstico confiável. HTTP 404 do ADN e `cStat=404` da NF-e permanecem conceitos distintos.

O motivo da NF-e está confirmado pelo retorno e pela reprodução do XML gerado. Para o ADN, o envio explícito é um ajuste de compatibilidade sustentado pelo contrato oficial e pela implementação já funcional; a confirmação da causa e da solução nessa instalação exige nova consulta após o deploy. O manual ainda documenta a modalidade sem parâmetro: não se afirma que o CNPJ seja formalmente obrigatório em todos os ambientes ou versões da API.

## Preservação

- Base da correção: `develop` **0.9.0-dev.62**, incluindo a automação por empresa da PR #87.
- Nenhuma migração, tabela, chave criptográfica, credencial ou certificado é alterado.
- Mantidos originais, recibos idempotentes, cursores, isolamento por empresa/ambiente, leases e pausas existentes.
- Não há reset de NSU, mudança automática de ambiente, manifestação, emissão ou escrituração.
- Reabrir um recibo antigo permanece uma leitura local. Uma consulta corrigida precisa de nova tentativa, após o intervalo vigente; reutilizar a chave antiga reproduz o recibo preservado.

## Validação

`tests/test_reception_request_regressions.py` reproduz com dados sintéticos:

- prefixos na área NF-e em produção e homologação, além dos URIs e caminho SOAP;
- CNPJ explícito no ADN para o próprio titular, matriz/filial e procuração, nos dois ambientes;
- recusa sem erros em HTTP 200/400, sem autorização ou avanço do cursor, com original íntegro;
- páginas positivas sucessivas, gravação dos XMLs antes do NSU e retomada;
- rejeição NF-e 404, idempotência, pausa e retomada de uma consulta corrigida.

As fixtures existentes passam a refletir `CnpjBase` no caso explícito. A regressão de ajuste manual de NSU verifica o valor XML pelo namespace, sem exigir o prefixo que provocava a recusa. As validações de XSD oficial, A1, mTLS sintético, permissões, empresas, cursores e automação existentes permanecem ativas.

Resultados locais e CI estão na descrição da PR. A suíte Apple efetiva precisa de macOS; não é validada por execução Linux. Consultas fiscais reais posteriores à correção dependem de deploy.

## Implantação e conferência

1. Integrar a PR após os checks e publicar pela pipeline existente; atualizar o serviço instalado para a imagem/versão que contenha este commit.
2. Confirmar a versão carregada no navegador. Não limpar banco, originais, recibos, cofre ou NSU.
3. Na NFS-e, iniciar nova consulta. Conferir `DOCUMENTOS_LOCALIZADOS`, perfil `CnpjBase`, XMLs arquivados e avanço do NSU; seguir páginas até ausência explícita ou pausa. Se a recusa persistir, conservar o novo original para diagnóstico do serviço, sem simular sucesso.
4. Na NF-e, aguardar a pausa já registrada e consultar novamente. A requisição corrigida não deve produzir a rejeição de namespace. Outros códigos de autorização, disponibilidade ou consumo devem ser tratados conforme o retorno, sem removê-los por suposição.
5. Conferir emitidas e recebidas NFS-e pelo CNPJ completo do XML e os arquivos disponíveis. Na NF-e, a distribuição não entrega ao próprio emitente o XML de sua nota; as emitidas completas precisam dos XMLs do emissor pelo fluxo de importação/integração. Não confundir essa limitação com a falha de namespace.

Não houve acesso administrativo ao host, alteração do serviço implantado ou consulta fiscal com o código corrigido nesta validação. O diagnóstico ao vivo confirmou as recusas da versão instalada; a PR entrega a correção pronta para implantação.

## Fontes oficiais

- [NT 2014.002 — distribuição NF-e e rejeição 404](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=0rPhVp1wRqc%3D).
- [MOC — regra D02, uso de prefixo no namespace](https://moc.sped.fazenda.pr.gov.br/NFe_NFCe/NFe_NFCe/RegrasDeValida%C3%A7%C3%A3o.html).
- [Manual ADN contribuintes v1.1 — GET DFe, parâmetros e perfis](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-municipios-apis-adn-sistema-nacional-nfs-e-v1-1-20261103.pdf/@@download/file).
