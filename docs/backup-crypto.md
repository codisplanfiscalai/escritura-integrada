# Proteção autenticada e recuperação local de backups

> Atualização: os limites atuais, limpeza gerenciada, protocolos por blocos e a camada Windows estão em [backup-reliability.md](backup-reliability.md). Números e restrições anteriores abaixo registram a etapa precedente.


Novas execuções gravam `.eibk`: envelope versionado com AES-256-GCM (tag de 128 bits, nonce aleatório de 96 bits). O cabeçalho autenticado contém apenas identificador não secreto da chave, modo de derivação, salt, nonce e tamanho. O conteúdo cifrado é o ZIP validado com manifesto e SQLite. O SHA-256 externo permanece no histórico para transporte/identificação; a autenticidade depende da tag GCM, não de um checksum editável. Usa `pycryptodomex==3.24.2`, já fixado por hash no runtime e agora declarado como dependência direta.

A API/UI aceita **somente o identificador da chave**, nunca a chave/senha. Falta de chave ou permissões inseguras bloqueia a execução; não existe downgrade automático para ZIP aberto. O histórico mostra o identificador por execução. ZIPs anteriores continuam restauráveis explicitamente conforme a configuração histórica, mas não recebem criptografia retroativa.

## Provisionamento e rotação (não executados em produção)

1. Crie um diretório de chaves **fora de `data_dir`**, pertencente ao usuário do processo, sem escrita para grupo/outros. No Docker, mantenha dados em `./data/app:/data` e UID/GID 10001:10001; provisione o segredo separadamente. Não altere o proprietário do banco operacional.
2. Como esse usuário, gere uma chave aleatória de 256 bits em arquivo novo:

   ```sh
   python -m app.backup_crypto keygen /diretorio-seguro/primary.key
   ```

3. Injete `ESCRITURA_BACKUP_KEYRING_DIR=/diretorio-seguro` no ambiente. Na tela, use o identificador `primary`. O arquivo deve ser regular, não symlink, privado (`0600` ou `0400`) e legível pelo processo. Arquivos com acesso de grupo/outros são recusados. Esta implementação verifica permissões POSIX; **ACL Windows ainda não homologada e o carregamento falha fechado nesse sistema**.
4. Preserve uma cópia offline segura da chave, separada dos arquivos de backup. Não registre conteúdo em logs, terminal, Git, tickets ou no próprio backup. Sem chave correta não há mecanismo de recuperação. Uma chave perdida não pode ser reconstruída a partir do pacote.
5. Para rotação, gere `rotacao-2026.key`, altere apenas o identificador na configuração e teste a recuperação de uma execução nova. Preserve as chaves anteriores enquanto existirem arquivos associados. A chave é carregada pelo identificador autenticado do arquivo na recuperação; alterar a configuração atual não invalida arquivos antigos.

O arquivo de chave é um segredo não cifrado protegido por permissões. O diretório/backup offline das chaves precisa de proteção do SO, criptografia de armazenamento ou cofre externo conforme a implantação; não foi implementado um KMS. Não se deve montar o chaveiro no bucket de backup. Não foi testada uma conta cloud nem um container de produção.

## Frase secreta opcional

O padrão recomendado é chave aleatória. `keygen --passphrase` solicita a frase duas vezes, sem eco, apenas em terminal interativo; não recebe senha por argumento nem stdin canalizado. O arquivo externo guarda a frase secreta privada, necessária ao agendamento sem intervenção. O modo usa scrypt (N=131072, r=8, p=1, salt aleatório de 128 bits por envelope) para derivar 32 bytes e depois AES-256-GCM. Parâmetros fixos impedem custo arbitrário vindo do cabeçalho. Consome aproximadamente 128 MiB no KDF, além da aplicação. O limite mínimo de 20 bytes não mede entropia: use frase longa e aleatória. Não há garantia contra ataque de dicionário a frases fracas.

Para recuperação de arquivo desse modo, pode-se usar `--password` em vez de `--key-file`. A senha é solicitada sem eco. A opção é recusada sem terminal interativo. Não inclua a senha no comando.

## Recuperação isolada e testável

```sh
python -m app.backup_crypto restore /copia/arquivo.eibk /pai-existente/nova-pasta --sha256 CHECKSUM_DO_HISTORICO --key-file /chaves/primary.key
```

O diretório final deve ser novo. O processo valida tamanho e SHA-256, descriptografa para staging privado e verifica a tag GCM **antes de criar o destino de recuperação**. Depois verifica o ZIP, manifesto, checksums internos e integridade SQLite. Chave/senha errada, modificação de cabeçalho/ciphertext/tag, truncamento e bytes excedentes são recusados. Diretório existente nunca é sobrescrito, mesmo quando a senha está incorreta. Não há ativação, religamento ou troca do banco em produção.

Os testes cobrem também alteração maliciosa do checksum externo: modificar o arquivo e recalcular SHA-256 não permite contornar a autenticação. O segredo não é serializado no envelope, histórico ou manifesto. Nonces aleatórios fazem duas criptografias do mesmo ZIP produzirem arquivos diferentes.

**Limites locais:** snapshot, ZIP intermediário e staging de descriptografia usam disco temporário em diretórios `0700`, arquivos `0600`. São removidos em sucesso/erros normais; queda abrupta pode deixar resíduos privados. Esta solução não cifra toda a área de trabalho nem garante apagamento físico em SSD, swap, crash dump ou memória Python. Use proteção de disco e procedimento local de inspeção/limpeza após interrupção. Uma restauração bem-sucedida é, por definição, um SQLite aberto com acesso restrito.

## Tamanho e provas realizadas

Mantidos os limites de 150 MiB **incluindo overhead criptográfico** e 2 GiB para SQLite descompactado. Não há aumento não comprovado de capacidade nem upload multipart. `scripts/backup_size_probe.py` usa apenas SQLite sintético e devolve métricas sem segredos/payloads:

| Payload sintético | SQLite | Envelope | Geração / recuperação nesta execução |
|---|---:|---:|---:|
| 8 MiB repetitivos | 13.36 MB | 0.26 MB | 0.20 s / 0.05 s |
| 8 MiB aleatórios | 13.36 MB | 8.64 MB | 0.30 s / 0.06 s |
| 64 MiB aleatórios | 72.16 MB | 67.44 MB | 2.60 s / 0.47 s |
| 148 MiB aleatórios | 160.35 MB | 155.63 MB | 5.90 s / 0.72 s |

Em todos, o conteúdo recuperado coincidiu por SHA-256. Um payload de 150 MiB foi recusado antes de criar ciphertext porque o envelope excederia o limite. Os tempos são observações locais, sem garantia de SLA e sem custo de rede. Na etapa histórica desta tabela ainda não havia ensaio de SQLite de 2 GiB; ele foi executado posteriormente e está em `backup-reliability.md`. Consumo máximo de RAM/disco sob concorrência fiscal, multipart e throughput cloud continuam não homologados. A prova sintética de entrada de 2 GiB não garante capacidade para todo conteúdo/carga. Ensaios com limite reduzido verificam a recusa de SQLite/extração acima do máximo.

## Regressões reproduzíveis

```sh
python -m unittest tests.test_backups tests.test_backup_crypto tests.test_maintenance tests.test_deploy_storage tests.test_infrastructure -v
python scripts/backup_size_probe.py
python scripts/browser_backups.py
python scripts/browser_pdf_probe.py
```

O teste de navegador substitui o uploader no processo de teste, usa chave sintética temporária separada de `data_dir` e não transmite dados externamente. O probe PDF diagnostica o endpoint e a capacidade do navegador; não transforma ausência de visualizador em aprovação de renderização.

## Investigação da prévia PDF

O probe isolado retornou HTTP 200, `application/pdf`, disposição `inline` e um PDF legível com uma página pelo pypdf. No Chromium Headless Shell 141 disponível, `navigator.pdfViewerEnabled` foi `false`; a janela foi criada, mas não se observaram eventos de DOM pronto nem download durante a janela diagnóstica de três segundos. O smoke original espera `DOMContentLoaded` do popup e havia expirado em 30 segundos. A evidência separa geração válida do PDF da visualização não comprovada nesse navegador; é compatível com falta de leitor embutido, sem provar a causa em todos os navegadores.

Foi avaliada também a expectativa de download automático no navegador sem leitor, que não se confirmou. Essa alteração experimental no teste foi descartada: `scripts/browser_exports.py` permanece original. Não houve relaxamento de assertions nem mudança no produto para mascarar a falha. Chromium completo continua impedido pelo EPERM de sockets Unix neste executor; não se contornou essa restrição. A renderização/impressão final precisa de teste em navegador com leitor PDF funcional.
