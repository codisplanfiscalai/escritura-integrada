# Operação e contratos da expansão 0.5

## Cadastros e consultas

Cadastros auxiliares são isolados por empresa: participantes (cliente, fornecedor, transportador e outros), estabelecimentos da mesma raiz de CNPJ, produtos, serviços, históricos e modelos contábeis. Edições exigem a versão lida; identidades CPF/CNPJ não são trocadas para reaproveitar um cadastro existente. Empresa ativa e competência ficam separadas da edição cadastral.

Os formulários de empresas, estabelecimentos e participantes compartilham a consulta. Documentos usam esses cadastros para evitar redigitação. A resposta nunca substitui campos automaticamente: compare **Atual / Consultado**, selecione os campos e aplique. O regime tributário e a IE principal não são escolhidos pelo provedor. Inscrições por UF têm número, situação, fonte e data. `unknown` = ausente/não informado; `not_found` = não localizado naquela consulta; `exempt` = isento confirmado pelo operador. São estados diferentes.

| Provedor | Uso / contrato | Política da aplicação |
|---|---|---|
| CNPJ.ws pública | CNPJ; IE conforme cobertura; cadastro pode estar em cache na origem | Até 3 requisições/minuto por instalação; timeout 4 s por tentativa |
| CNPJ.ws comercial | Opcional com token do escritório | `ESCRITURA_CNPJWS_TOKEN` somente no backend; mantém limite conservador |
| ReceitaWS pública | CNPJ, sem presumir cobertura completa de IE | Alternativa; até 3/minuto |
| BrasilAPI | CNPJ e CEP v2 | Alternativa; CNPJ 3/minuto e CEP 30/minuto por instalação |
| ViaCEP | CEP, logradouro, bairro, município, UF e IBGE | Preferencial de CEP; 30/minuto por instalação |

Cache persistente de 24 horas; resposta antiga pode ser apresentada **marcada como desatualizada** quando a rede falha. HTTP 429 respeita `Retry-After` com limite de espera até 24 h. Máximo de 1 MB por resposta. Endpoints fixos sem redirecionamento; não há URL arbitrária enviada pelo formulário. CPF não é consultado em provedor de CNPJ. CNPJ alfanumérico continua aceito manualmente; a consulta online dessa variante não está anunciada sem contrato confirmado dos provedores.

Cobertura de IE documentada pelo CNPJ.ws na consulta desta etapa: BA, GO, MG, PB, PR, PE, RS, SC, SP e SE; a cobertura pode mudar. Uma resposta parcial ou vazia não prova inexistência, isenção, atividade ou enquadramento fiscal. O escritório deve avaliar atualização, condições e eventual contratação. O núcleo local funciona sem essas APIs.

Documentação consultada em 07/11/2026: [CNPJ.ws pública](https://docs.cnpj.ws/referencia-de-api/api-publica/consultando-cnpj), [inscrições estaduais](https://docs.cnpj.ws/modelos-de-dados/inscricoes-estaduais), [ReceitaWS](https://developers.receitaws.com.br/), [BrasilAPI](https://brasilapi.com.br/docs), [ViaCEP](https://viacep.com.br/).

## Fluxos e efeitos

1. **Importar:** selecionar origem/opções → analisar → diagnosticar → confirmar. O original fica armazenado com hash. Documentos entram pendentes; não geram títulos ou partidas por si sós.
2. **Escriturar:** editar → conferir → escolher modelo/partidas e, opcionalmente, parcelas → confirmar. Todos os efeitos são gravados na mesma transação. Soma das parcelas deve coincidir com o valor financiado. Repetir a mesma operação não repete os efeitos.
3. **Reverter escrituração:** desfazer primeiro conciliações/baixas/acordos dependentes. A reversão cancela títulos não movimentados, estorna a partida vinculada e devolve o documento à conferência. O original permanece no histórico.
4. **Baixar:** principal abate o saldo; caixa = principal + juros + multa − desconto. Contabilizar é uma escolha explícita com contas para cada componente. Estornar recompõe o saldo e cria a partida inversa quando aplicável.
5. **Renegociar:** selecionar títulos com saldo do mesmo participante e sentido → revisar encargos/desconto → distribuir parcelas. Os originais ficam encerrados e os novos mantêm a origem no acordo. Não há contabilização implícita de encargos negociados. A reversão do acordo exige desfazer antes os movimentos dos novos títulos.
6. **Conciliar:** o vínculo individual apenas concilia. Rateios permitem múltiplos títulos por movimento e vínculos parciais do título em vários movimentos. A opção **Também registrar baixas** é explícita, usa a data bancária e não calcula encargos nem gera contabilidade. Desfazer vínculo preserva a baixa; estorne-a no Financeiro quando necessário.
7. **Fechar:** fiscal e contábil são independentes. Escriturar fiscal+contábil requer ambos abertos. Reabrir exige justificativa e mantém auditoria. Uma baixa sem contabilidade não é escrituração contábil e não altera livros fechados.

Valores são armazenados em centavos; cálculos de taxa usam `Decimal` e `ROUND_HALF_UP`. SQLite em WAL usa escrita serializada (`BEGIN IMMEDIATE`); versões protegem cadastros/documentos e saldos são verificados sob lock. Permissões e contexto são reavaliados depois da obtenção do lock.

## Importadores e relatórios

O perfil XML continua limitado a NF-e/NFC-e e CT-e previstos no leitor; assinatura, autorização e XSD não são homologados pelo parser. EFD ICMS/IPI abrange os registros documentados em `tests/fixtures/README.md`, com C100/C170/C190 e faturas C140/C141; não abrange toda EFD. TXT/CSV exigem mapeamentos e convenções válidos. OFX/QFX, OFC e QIF aceitam os perfis testados; ambiguidade produz diagnóstico.

ZIP/7z/RAR: máximo 20 MiB por arquivo/membro, 1.000 membros, dois níveis de contêiner, limite global e proporção de expansão do parser. Leitura em memória, sem extrair caminhos dos membros para disco. Senhas, multipartes, links e caminhos inseguros são recusados. RAR sem compressão é lido em Python; RAR comprimido depende de libarchive (`bsdtar` incluído no Docker; `tar.exe` no Windows 10/11). Ausência do leitor ou codec não suportado bloqueia a confirmação e oferece diagnóstico. Teste local não comprova todas as variantes RAR4/RAR5.

Relatórios oferecem intervalo, conta/centro quando aplicável, documento/participante/histórico, situação e operação conforme o tipo. CSV contém todas as linhas; impressão/PDF do navegador também. Os filtros não aplicáveis a um tipo não mudam seu cálculo. Balanço e DRE exigem classificação explícita das contas movimentadas. Saldos iniciais são lançamentos balanceados; para integrarem saldo anterior, sua data deve preceder o início do relatório. Os demonstrativos são internos e não equivalem a peças legais homologadas.

## Prosoft

A tela prepara CTBLCTOS LC1/LC2 da competência ativa. Cada acesso contábil, centro e política de terceiro precisa ser conferido com o cadastro de destino. Contas com terceiros diferentes a cada partida exigem exportação por seleção/perfil adequado; não se presume equivalência por nome. A prévia lista origens, totais e conversões ASCII. Textos extensos são recusados, sem truncamento. Alterar registros/mapeamentos invalida a prévia; o arquivo confirmado é imutável e tem SHA-256.

Não há gravação na base Prosoft. Conferir registros e totais no importador da instalação de destino é etapa operacional pendente. O perfil não exporta livros fiscais, CTA, TRC ou SLD.

## Distribuição

`main` mantém a versão estável. `develop` mantém uma pré-release contínua superior. O lock comum inclui os leitores de arquivo para Windows/Docker. O tray permanece sem serviço Windows, com abrir/iniciar/parar/reiniciar e preferência de início minimizado. Imagens opcionais de PostgreSQL, MySQL, Redis e MinIO permanecem infraestrutura independente; nenhum adaptador foi declarado pronto.
