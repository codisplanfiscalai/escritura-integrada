# Backup remoto: composição para revisão em PR draft

Base sincronizada: `develop` dev.23, `67a5e2e0b3c65fe7948827d6d66da5361970bfb1`.
A frente local anterior termina em `ed2dff2c5ba2b60b119dccce6329976842a156c7`; o merge local `67d2b42d207b52ff9a99d982efcd2c5ec07435d9` preserva esse histórico. O único conflito foi `requirements.txt`, resolvido mantendo `cryptography` do develop e `pycryptodomex` direto do backup, ambos já fixados no lock do runtime. Nenhum workflow foi alterado em relação à base. Não se incorporou branch paralela ainda não integrada ao develop.

## Comportamento incluído

Interface administrativa, um destino por instalação (Dropbox/Drive/S3/MinIO), referências externas de credenciais/chaves, execução manual e por intervalo, fila persistida, idempotência, bloqueio local, histórico, cancelamento antes de upload e erros sem respostas brutas do provedor. Snapshot SQLite/WAL consistente e sanitizado, manifesto/checksums, AES-256-GCM, validação local antes de upload e recuperação exclusivamente para destino novo. Limites: SQLite 2 GiB e envelope 512 MiB, dependendo da compressibilidade. Retenção sem exclusão automática; limpeza lógica restrita a temporários próprios marcados.

O código de recepção integrado no develop carrega A1 de diretório externo; o backup percorre somente o SQLite operacional, não esse diretório. Arquivos de certificados, chaveiro, variáveis, configuração de controle e caches externos não são varridos. A recusa de extensões/marcadores conhecidos dentro de originais não é detecção universal de segredos disfarçados; dados fiscais e hashes de senha permanecem no conteúdo cifrado.

## Evidências da composição local

No código do merge `67d2b42`, antes das correções documentais:

- `.venv-backup/bin/python -m unittest tests.test_backups tests.test_backup_crypto tests.test_backup_reliability tests.test_backup_space -v`: 42 executados, 41 passaram, 1 skip nativo Windows, 8,958 s.
- `node --test frontend/tests/*.test.js`: 180 passaram, zero falhas/skips.
- `npm run build --prefix frontend`: aprovado, 4,14 s; aviso existente de bundle acima de 500 kB.
- `ESCRITURA_TEST_BROWSER=<headless-shell-local> .venv-backup/bin/python scripts/browser_backups.py`: quatro formulários, salvar agenda, cancelar confirmação, backup manual, recuperação isolada, recusa de repetição, mobile e ausência de erros JS aprovados. Servidor, dados e uploader sintéticos, sem rede cloud.
- Dependências do runtime instaladas com hashes, `pip check` sem incompatibilidades; diff-check aprovado.
- Revisão dos 57 blobs introduzidos no histórico local: nenhum banco, pacote de backup, arquivo de chave/certificado ou padrão conhecido de token encontrado. Maior blob 30.226 bytes. Isso complementa a revisão do diff, não constitui garantia universal de ausência de segredos.

O gate agregado deve ser consultado no head exato publicado; resultados e bloqueios atuais serão descritos na PR. Comando: `python -m scripts.ci.checks --version 0.9.0-dev.23 --source-sha SHA_DO_HEAD --output artifacts/backup-publication/linux-checks.json`. Os artefatos locais ignorados pelo Git não são enviados com o código.

## Resultados históricos, não aprovação do head sincronizado

No commit `ed2dff2`, o gate contou 1.057 testes, zero falhas de asserção, três erros EPERM em sockets Unix do atualizador Docker e 29 skips. Esse gate não estava verde. Nenhuma restrição foi contornada nem teste mascarado.

O ensaio opt-in de SQLite de exatamente 2 GiB e payload altamente compressível passou com origem preservada, hashes conferidos e destino existente recusado; extração resultou em banco 4 KiB menor após sanitização/VACUUM. Origem de 2 GiB + 4 KiB foi recusada. Payload aleatório de 520 MiB excedeu o orçamento do envelope e foi recusado com limpeza. Valores e método em [backup-reliability.md](backup-reliability.md). Não foi repetido na composição com dev.23.

## Condições antes de produção

- Provedores exercitados por contrato e transporte simulado: falta homologação autorizada de conta, permissões, quota, rede e versão MinIO. OAuth inicial e provisionamento de segredos são externos. S3/MinIO podem exigir GetObject/KMS para confirmar checksum por HEAD.
- Windows DPAPI/ACL e empacotamento nativo não homologados neste Linux; teste correspondente permanece skip. A política CI que separa develop (GHCR) de main (binários + GHCR) pertence a outra frente. Esta PR não deve ser integrada antes da aplicação dessa política e da revisão dos checks do head.
- Não há liderança distribuída, retomada persistente de upload, rotação automática, retenção destrutiva ou download/restauração cloud automática. Upload incerto exige conferência do destino antes de nova intenção.
- A UI recupera a cópia local; para desastre do host é necessário obter o envelope do destino por meio autorizado e usar a CLI com a chave preservada fora do backup. Sem chave/frase correta não há recuperação.
- Sem garantia de apagamento físico, capacidade para qualquer banco de 2 GiB, ativação automática ou rollback. Não houve acesso a dados reais, VPS, merge, release ou deploy.
