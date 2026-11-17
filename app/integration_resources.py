"""Explicit integration projections. No arbitrary table/column or raw-blob access."""
from dataclasses import dataclass
import re

from .core import DomainError
from .permissions import require


@dataclass(frozen=True)
class Resource:
    table: str
    routine: str
    fields: str
    version: str = ''
    predicate: str = '1'
    identity: str = '{p}id'
    company: str = 'company_id'
    period: str = ''
    events: bool = True
    text_key: bool = False

    def sql(self, expression, prefix='r.'):
        return expression.format(p=prefix)


RESOURCES = {
    'cost-centers': Resource('cost_centers','accounting.cost_centers','code name active version','version'),
    'company': Resource('companies','system.companies','code name trade_name tax_id regime state city version','version',company='id'),
    'accounts': Resource('effective_accounts','accounting.accounts','access_code classifier name nature analytical requires_cost_center active version report_group prosoft_code','version',events=False),
    'journals': Resource('journals','accounting.journals','number date period document history total_cents reversal_of reversed_by created_at',period='period'),
    'journal-lines': Resource('journal_lines','accounting.journals','journal_id position account_id debit_cents credit_cents cost_center_id participant_id'),
    'documents': Resource('documents','fiscal.documents','direction number series model issue_date posting_date period partner_name partner_tax_id key cfop total_cents status version journal_id','version',period='period'),
    'titles': Resource('titles','financial.titles','kind description partner_name document issue_date due_date amount_cents paid_cents document_id version participant_id cancelled renegotiation_id installment','version',period='issue_date'),
    'settlements': Resource('settlements','financial.settlements','title_id date amount_cents journal_id interest_cents fine_cents discount_cents cash_cents reversed_at reversal_date reversal_journal_id',period='date'),
    'bank-transactions': Resource('bank_transactions','financial.reconciliation','bank_account date amount_cents description reference external_id',period='date'),
    'reconciliations': Resource('reconciliations','financial.reconciliation','transaction_id title_id created_at'),
    'bank-allocations': Resource('bank_allocations','financial.reconciliation','transaction_id title_id amount_cents settlement_id created_at reversed_at'),
    'renegotiations': Resource('renegotiations','financial.titles','date principal_cents interest_cents discount_cents created_at reversed_at',period='date'),
    'catalogs': Resource('catalogs','fiscal.parameters','kind code description direction valid_from valid_to active version','version'),
    'rules': Resource('rules','fiscal.parameters','family_id version name tax rate direction cfop ncm valid_from valid_to status active superseded_by regime state municipality','version'),
    'fiscal-imports': Resource('imports','fiscal.imports','filename sha256 period status created_at',period='period'),
    'assessments': Resource('tax_assessments','fiscal.assessments','period tax source responsible fingerprint created_at',period='period'),
    'tax-adjustments': Resource('tax_adjustments','fiscal.assessments','period tax kind amount_cents document_id reversed_at category',period='period'),
    'tax-ledgers': Resource('tax_ledgers','fiscal.assessments','period tax assessment_id previous_id opening_credit_cents carry_credit_cents payable_cents reversed_at reversed_by',period='period'),
    'auditor-jobs': Resource('auditor_jobs','auditor.analyses','year mode start end status version cancelled created_at finished_at name stage progress processed_files total_files parent_id started_at','version',predicate='{p}deleted_at IS NULL'),
    'auditor-catalogs': Resource('auditor_catalogs','auditor.catalogs','name version state source valid_from valid_to sha256 created_at published_at parent_id','version'),
    # Audit delivery must never generate another audit delivery recursively.
    'audit': Resource('audit','system.audit','actor action entity entity_id created_at',events=False),
}
for name, kind, routine in (
    ('participants','participant','fiscal.masters'),
    ('products','product','fiscal.masters'),
    ('services','service','fiscal.masters'),
    ('establishments','establishment','fiscal.masters'),
    ('histories','history','accounting.histories'),
    ('accounting-models','accounting_model','accounting.histories'),
):
    RESOURCES[name] = Resource('masters',routine,'kind code name tax_id active version created_at updated_at','version',predicate="{p}kind='"+kind+"'")
for module in ('fiscal','accounting','financial','social'):
    RESOURCES[module+'-periods'] = Resource('period_locks',module+'.periods','module period closed changed_at version','version',predicate="{p}module='"+module+"'",identity="{p}module || ':' || {p}period",period='period',text_key=True)
    RESOURCES[module+'-exercises'] = Resource('exercises',module+'.periods','module year created_at',predicate="{p}module='"+module+"'",identity="{p}module || ':' || {p}year",text_key=True)
for module in ('accounting','financial'):
    RESOURCES[module+'-imports'] = Resource('module_imports',module+'.imports','module year layout file_id created_at',predicate="{p}module='"+module+"'")


def resource(name):
    if not isinstance(name,str) or name not in RESOURCES:
        raise DomainError('Recurso de integração não disponível.',404,'integration_resource_not_found')
    return RESOURCES[name]


def scope_for(name, mode):
    spec = resource(name)
    if mode != 'read' and not spec.events:
        raise DomainError('Este recurso não oferece eventos.',422,'integration_events_unavailable')
    if name == 'cost-centers':
        return {'read':'cost-centers:read','events':'events:read','webhooks':'webhooks:deliver'}[mode]
    return name+':'+mode


SCOPES = {scope_for(name,mode):(name,spec.routine)
          for name,spec in RESOURCES.items()
          for mode in ('read','events','webhooks') if mode == 'read' or spec.events}


def authorize_scope(conn, uid, cid, scope):
    if scope not in SCOPES:
        raise DomainError('Escopo inválido.',422,'invalid_scope')
    for action in ('read','export'):
        require(conn,uid,cid,SCOPES[scope][1],action)


def subscriptions(value):
    names = value if isinstance(value,list) else [value]
    if not names or len(names) > 40:
        raise DomainError('Selecione de 1 a 40 recursos.',422,'invalid_subscription')
    for name in names:
        scope_for(name,'events')
    return sorted(set(names))


def event_type(name):
    return ('cost-center' if name == 'cost-centers' else name)+'.changed.v1'


def page(conn, cid, name, after=None, limit=100, period=None, item=None):
    spec = resource(name)
    key = spec.sql(spec.identity)
    fields = ','.join('r.'+field for field in spec.fields.split())
    where = [f'r.{spec.company}=?','('+spec.sql(spec.predicate)+')']
    args = [cid]
    cursor = item if item is not None else after
    if cursor is not None:
        try:
            if spec.text_key:
                if not isinstance(cursor,str) or not 1 <= len(cursor) <= 80:
                    raise ValueError()
            else:
                if isinstance(cursor,bool) or not re.fullmatch(r'-?\d{1,20}',str(cursor)):
                    raise ValueError()
                cursor = int(cursor)
                if not -(2**63) <= cursor < 2**63:
                    raise ValueError()
        except (ValueError,TypeError):
            raise DomainError('Cursor/ID inválido.',422,'invalid_cursor')
        where.append(key+('=?' if item is not None else '>?'))
        args.append(cursor)
    if period is not None:
        if not spec.period or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',period):
            raise DomainError('Competência inválida ou não suportada neste recurso.',422,'invalid_period')
        where.append(f'substr(r.{spec.period},1,7)=?')
        args.append(period)
    rows = [dict(r) for r in conn.execute(f'SELECT {key} AS id,{fields} FROM {spec.table} r WHERE '+ ' AND '.join(where)+f' ORDER BY {key} LIMIT ?', (*args,limit))]
    return {'version':'1','resource':name,'items':rows,'next_cursor':rows[-1]['id'] if rows else after}


def migrate(conn):
    """Add resource discrimination without changing legacy events or subscriptions."""
    for table in ('integration_events','integration_webhooks'):
        if 'resource' not in {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN resource TEXT NOT NULL DEFAULT 'cost-centers'")
    conn.execute('CREATE INDEX IF NOT EXISTS integration_events_resource ON integration_events(company_id,resource,seq)')
    conn.execute('''CREATE TABLE IF NOT EXISTS integration_redrives(
        webhook_id TEXT NOT NULL,event_seq INTEGER NOT NULL,key TEXT NOT NULL,request_hash TEXT NOT NULL,
        created REAL NOT NULL,PRIMARY KEY(webhook_id,event_seq,key),
        FOREIGN KEY(webhook_id,event_seq) REFERENCES integration_deliveries(webhook_id,event_seq))''')
    for name,spec in RESOURCES.items():
        if not spec.events or name == 'cost-centers':
            continue
        # A row leaving a filtered resource becomes a tombstone; the new resource
        # receives a created event. Both happen in the business transaction.
        def insert(prefix,operation):
            return f"""INSERT INTO integration_events(id,company_id,resource_id,version,operation,created,resource)
                VALUES(lower(hex(randomblob(16))),{prefix}{spec.company},{spec.sql(spec.identity,prefix)},
                {prefix+spec.version if spec.version else '0'},'{operation}',strftime('%Y-%m-%dT%H:%M:%fZ','now'),'{name}');"""
        new,old = spec.sql(spec.predicate,'NEW.'),spec.sql(spec.predicate,'OLD.')
        same = f'NEW.{spec.company}=OLD.{spec.company} AND {spec.sql(spec.identity,"NEW.")}={spec.sql(spec.identity,"OLD.")}'
        triggers = [('insert','INSERT',new,insert('NEW.','created')),
                    ('delete','DELETE',old,insert('OLD.','deleted')),
                    ('update','UPDATE',f'({new}) AND ({old}) AND ({same})',insert('NEW.','updated')),
                    ('leave','UPDATE',f'({old}) AND (NOT ({new}) OR NOT ({same}))',insert('OLD.','deleted')),
                    ('enter','UPDATE',f'({new}) AND (NOT ({old}) OR NOT ({same}))',insert('NEW.','created'))]
        for suffix,operation,when,body in triggers:
            trigger = 'integration_resource_'+name.replace('-','_')+'_'+suffix
            conn.execute(f'CREATE TRIGGER IF NOT EXISTS {trigger} AFTER {operation} ON {spec.table} WHEN {when} BEGIN {body} END')
