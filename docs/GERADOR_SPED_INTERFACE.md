# Interface do gerador SPED parcial

Fiscal → Gerador SPED expõe a API existente de Bloco C a partir da escrituração.
Somente NFC-e próprias de saída escrituradas pertencem ao recorte atual. A tela
exige escolha explícita de perfil, atividade e finalidade; não os presume pelo
cadastro. Consolidação diária/série é opcional e desligada por padrão. Ela altera
apenas o arquivo operacional, nunca os documentos ou lançamentos persistidos.

A geração mostra quantidade incluída/excluída, motivos e avisos. TXT é baixado
sem recodificação dos bytes ISO-8859-1 retornados. JSON separado preserva resumo,
referências/versões, avisos, exclusões e hashes, excluindo a cópia base64 do TXT.
Não há transmissão, assinatura, apuração nova ou alegação de EFD/PVA completa.
ECD, ECF e Contribuições permanecem explicitamente sem geradores completos.

O controle mantém o resultado ao desativar/reativar a view no mesmo contexto,
mas cancela espera pendente. Mudança de empresa, competência, usuário ou
permissões limpa parâmetros/resultado. Mudança de parâmetros descarta o arquivo
anterior. Respostas antigas e cliques repetidos não repovoam estado ultrapassado.
Leitura e exportação de documentos fiscais são obrigatórias; API mantém suas
verificações de empresa, competência, CSRF e autorização. Cancelar espera não
altera documentos: a geração é somente leitura.

Testes unitários do controlador cobrem cancelamento, retorno, concorrência,
alteração de parâmetros/contexto e perda de permissão. O roteiro Chromium
browser_reports.py acrescenta geração real, comparação dos bytes TXT/JSON e
capturas desktop/mobile, sem substituir respostas do backend.
