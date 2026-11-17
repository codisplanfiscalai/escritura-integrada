"""Company-owned reception defaults and an opaque dispatch snapshot (no secrets)."""
import json
from .core import DomainError, company_row, digest

SETTINGS = 'reception-company-preferences-v1'
ENVIRONMENT_KEYS = {'nfe_distribution':'nfe_environment', 'nfse_adn':'nfse_environment'}

def preferences(conn, cid):
    row = conn.execute('SELECT result_json FROM operations WHERE company_id=? AND scope=? AND key=?',
                       (cid, SETTINGS, 'defaults')).fetchone()
    return json.loads(row['result_json']) if row else {
        'version':0, 'nfe_environment':'homologation', 'nfse_environment':'restricted_production'}

def configuration(conn, cid, provider, credentials):
    if provider not in ENVIRONMENT_KEYS:
        raise DomainError('Serviço inválido.')
    company = company_row(conn, cid)
    prefs = preferences(conn, cid)
    environment = prefs[ENVIRONMENT_KEYS[provider]]
    credential = credentials.revision(conn, cid) if hasattr(credentials, 'revision') else None
    revision = digest({'company':cid, 'provider':provider, 'tax_id':company['tax_id'],
                       'state':company['state'], 'preferences':prefs, 'credential':credential})
    return {'environment':environment, 'revision':revision}

def require_configuration(conn, cid, provider, credentials, expected, environment=None):
    current = configuration(conn, cid, provider, credentials)
    if (not isinstance(expected, str) or current['revision'] != expected
            or environment is not None and current['environment'] != environment):
        raise DomainError('A configuração da empresa mudou. Atualize a tela e confirme uma nova consulta. Nenhuma consulta foi enviada.',
                          409, 'stale_reception_configuration')
    return current
