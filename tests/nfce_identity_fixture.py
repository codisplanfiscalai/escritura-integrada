"""Shared synthetic candidate contract; no connection, credentials or real data."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
COLUMNS=('id','company_id','direction','model','series','number','partner_tax_id','extra_json','period')
TABLE_COLUMNS='id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, direction TEXT NOT NULL, model TEXT NOT NULL, series TEXT NOT NULL, number TEXT NOT NULL, partner_tax_id TEXT NOT NULL, extra_json TEXT NOT NULL, period TEXT NOT NULL'
OLD_QUERY="SELECT * FROM documents WHERE company_id=? AND direction=? AND model=? AND (? OR extra_json LIKE '%\"book_cancellation\"%')"


def fixture():
    value=json.loads((ROOT/'tests/fixtures/nfce_identity_lookup_ficticio.json').read_text(encoding='utf-8'))
    assert value['synthetic_only'];return value


def actual_query():
    tree=ast.parse((ROOT/'app/core.py').read_text(encoding='utf-8'))
    core=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Core')
    method=next(node for node in core.body if isinstance(node,ast.FunctionDef) and node.name=='_create_document')
    found=[node.args[0].value for node in ast.walk(method) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='execute' and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and node.args[0].value.startswith('SELECT * FROM documents WHERE') and 'book_cancellation' in node.args[0].value]
    assert len(found)==1
    assert "ltrim(number,'0')=ltrim(?,'0')" in found[0]
    return found[0]


def index_ddl(table='documents',name='idx_documents_cancellation_identity'):
    from app.db import SCHEMA
    statement=next(line for line in SCHEMA.splitlines() if line.startswith('CREATE INDEX IF NOT EXISTS idx_documents_cancellation_identity '))
    return statement.replace('idx_documents_cancellation_identity',name).replace(' ON documents(',f' ON {table}(')


def queries(table='documents',postgres=False):
    values=[query.replace('FROM documents WHERE',f'FROM {table} WHERE') for query in [OLD_QUERY,actual_query()]]
    # Native psycopg parameters, including literal-percent escaping in LIKE.
    return [query.replace('%','%%').replace('?','%s') for query in values] if postgres else values


def parameters(case,new=False):
    prefix=(case['company_id'],case['direction'],case['model'])
    return (*prefix,case['number'],case['cancellation']) if new else (*prefix,case['cancellation'])


def unchanged_guard_ids(rows,case):
    """Projection before existing payload-equality/conflict decision, not a new rule."""
    canonical=lambda value:str(int(value)) if value and value.isascii() and value.isdigit() else value
    tax=lambda value:re.sub(r'[.\-/\s]','',value).upper()
    selected=[]
    for raw in rows:
        row=dict(raw)
        if any(canonical(row[key])!=canonical(case[key]) for key in ('series','number')):continue
        prior=json.loads(row['extra_json']).get('book_cancellation')
        old_issuer,new_issuer=tax(row['partner_tax_id']),tax(case['partner_tax_id'])
        same=case['direction']=='outgoing' or not old_issuer or not new_issuer or old_issuer==new_issuer
        if same and (case['cancellation'] or prior):selected.append(row['id'])
    return sorted(selected)


def raw_digest(rows):
    return hashlib.sha256(json.dumps([dict(row) for row in rows],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
