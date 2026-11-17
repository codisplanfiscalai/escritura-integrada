"""Container-only A1 recovery fixture. Synthetic identities; no network calls.

Never use this fixture with an existing volume. The driver creates UUID-scoped
volumes and runs each step in a different, disposable, unprivileged container.
"""
from datetime import datetime, timedelta, timezone
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

from app import backup_crypto as crypto
from app.core import Core, DomainError, cnpj_digits
from app.db import Database
from app.reception_vault import CompanyA1Vault

VAULT = Path('/run/escritura/reception-vault')
TARGETS = [prefix + cnpj_digits(prefix) for prefix in ('112223330001', '112223330002')]


def private(path, raw):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(raw)


def copy_keys(source):
    files = list(Path(source).glob('*.key'))
    assert len(files) == 1
    for source in files:
        private(VAULT / source.name, source.read_bytes())


def seed(data):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates
    from cryptography.x509.oid import NameOID, ObjectIdentifier

    core = Core(Database(data / 'store'))
    core.setup({'username': 'fixture', 'password': 'Synthetic-local-admin-fixture-only'})
    with core.db.read() as conn:
        uid = conn.execute('SELECT id FROM users').fetchone()['id']
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SYNTHETIC NO FISCAL VALUE')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.OtherName(ObjectIdentifier('2.16.76.1.3.3'),
                           b'\x0c\x0e' + TARGETS[0].encode())]), critical=False).sign(key, hashes.SHA256()))
    password = 'Synthetic-A1-only-not-a-real-password'
    raw = serialize_key_and_certificates(b'SYNTHETIC', key, cert, None,
                                        serialization.BestAvailableEncryption(password.encode()))
    vault = CompanyA1Vault(core.db)
    for index, target in enumerate(TARGETS):
        company = core.create_company({'code': 'FIXTURE' + str(index), 'name': 'Synthetic fixture',
                                       'tax_id': target, 'state': 'SP', 'regime': 'outros'}, 'fixture')
        vault.save(company['id'], uid, 'fixture', raw, password, {
            'version': 0, 'environments': {'nfse_adn': ['restricted_production']}, 'allow_adn_procuration': False})
    # Fixture PFX/password exist only in memory and encrypted DB, never in output/files.
    return check(data)


def check(data, missing=False):
    import ssl
    db = Database(data / 'store')
    vault = CompanyA1Vault(db)
    with db.read() as conn:
        companies = conn.execute('SELECT id,tax_id FROM companies ORDER BY code').fetchall()
        before = [tuple(r) for r in conn.execute('SELECT request_hash,result_json FROM operations ORDER BY company_id,scope,key')]
    assert [c['tax_id'] for c in companies] == TARGETS
    for company in companies:
        try:
            identity = vault.load(company['id'], company['tax_id'], 'nfse_adn', 'restricted_production')
        except DomainError as error:
            assert missing and error.code == 'reception_vault_unavailable'
        else:
            assert not missing and identity.tax_id == TARGETS[0]
            assert identity.context.minimum_version >= ssl.TLSVersion.TLSv1_2
            assert identity.context.check_hostname and identity.context.verify_mode == ssl.CERT_REQUIRED
    with db.read() as conn:
        assert before == [tuple(r) for r in conn.execute('SELECT request_hash,result_json FROM operations ORDER BY company_id,scope,key')]
    assert not list(data.rglob('*.key'))
    return {'companies': len(companies), 'key_missing_refused': missing}


def backup(data, source_data=Path('/source-data'), source_vault=Path('/source-vault')):
    secret = crypto.Secret('raw', os.urandom(32))
    private(data / 'synthetic-envelope.key', secret.value)
    database = source_data / 'store/escritura.sqlite3'
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        sql = 'SELECT company_id,scope,key,request_hash,result_json FROM operations ORDER BY company_id,scope,key'
        before = conn.execute(sql).fetchall()
        checksum = crypto.build(database, data / 'synthetic.eibk', 'fixture', secret)
        assert conn.execute(sql).fetchall() == before
    (data / 'checksum.json').write_text(json.dumps(checksum))
    copy_keys(source_vault)
    return {'encrypted_database_backup': True, 'separate_key_copy': True}


def restore(data, source=Path('/source-backup'), source_vault=Path('/source-vault')):
    crypto.restore(source / 'synthetic.eibk', data / 'store', json.loads((source / 'checksum.json').read_text()),
                   secret=crypto.Secret('raw', (source / 'synthetic-envelope.key').read_bytes()))
    copy_keys(source_vault)
    return check(data)


def wrong_key(data):
    with Database(data / 'store').read() as conn:
        installation = conn.execute("SELECT value FROM meta WHERE key='reception_vault_id'").fetchone()['value']
    private(VAULT / (installation + '.key'), os.urandom(32))
    return check(data, missing=True)


if __name__ == '__main__':
    # Linux UID/modes are part of this test, not inferred from a mocked filesystem.
    assert os.getuid() == 10001 and VAULT.stat().st_uid == 10001 and VAULT.stat().st_mode & 0o777 == 0o700
    action = sys.argv[1]
    result = {'seed': seed, 'check': check, 'missing': lambda d: check(d, missing=True), 'wrong': wrong_key,
              'backup': backup, 'restore': restore}[action](Path('/data'))
    print(json.dumps({'action': action, 'ok': True, **result}))
