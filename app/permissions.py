"""Autorização por empresa: exceções pessoais, grupos e negação por padrão."""
from __future__ import annotations

import re

MODULES = {'fiscal': 'Fiscal', 'accounting': 'Contábil', 'financial': 'Financeiro', 'social': 'Social', 'auditor': 'Auditor Fiscal', 'system': 'Sistema'}
ACTIONS = {'read': 'Consultar', 'create': 'Incluir', 'edit': 'Editar', 'delete': 'Excluir/desativar',
           'import': 'Importar', 'export': 'Exportar', 'print': 'Imprimir', 'book': 'Escriturar',
           'settle': 'Realizar baixas', 'reverse': 'Estornar', 'close': 'Fechar', 'reopen': 'Reabrir'}
ROUTINES = {
    'fiscal.documents': ('Escrituração e documentos', 'read create edit delete book reverse export print'),
    'fiscal.imports': ('Importações fiscais', 'read import export delete'),
    'fiscal.masters': ('Cadastros fiscais', 'read create edit delete'),
    'fiscal.parameters': ('Parametrizações fiscais', 'read create edit delete'),
    'fiscal.assessments': ('Apurações e ajustes', 'read create edit reverse book export print'),
    'fiscal.reports': ('Livros e relatórios fiscais', 'read export print'),
    'accounting.journals': ('Lançamentos e saldos iniciais', 'read create edit delete book reverse export print'),
    'accounting.accounts': ('Plano de contas', 'read create edit delete'),
    'accounting.histories': ('Históricos e modelos contábeis', 'read create edit delete'),
    'accounting.cost_centers': ('Centros de custo', 'read create edit delete'),
    'accounting.reports': ('Livros e demonstrações', 'read export print'),
    'accounting.imports': ('Importações contábeis', 'read import export'),
    'financial.imports': ('Importação de títulos', 'read import export'),
    'auditor.analyses': ('Auditorias internas e avulsas', 'read create import edit delete export print'),
    'auditor.catalogs': ('Catálogos do Auditor', 'read create edit import book export'),
    'system.storage': ('Arquivos e integridade', 'read export'),
    'accounting.prosoft': ('Integração Prosoft', 'read export'),
    'financial.titles': ('Títulos a pagar e receber', 'read create edit reverse export print'),
    'financial.settlements': ('Baixas financeiras', 'read settle reverse'),
    'financial.reconciliation': ('Conciliação bancária e de participantes', 'read import edit reverse export print'),
    'financial.reports': ('Relatórios financeiros', 'read export print'),
    'system.companies': ('Cadastro da empresa', 'read edit'),
    'system.audit': ('Auditoria da empresa', 'read export'),
}
for _module in ('fiscal', 'accounting', 'financial', 'social'):
    ROUTINES[_module + '.periods'] = ('Exercícios e competências', 'read create close reopen')


def catalog():
    return {'modules': MODULES, 'actions': ACTIONS,
            'routines': [{'id': key, 'module': key.split('.')[0], 'name': title, 'actions': actions.split()}
                         for key, (title, actions) in ROUTINES.items()],
            'precedence': ['administrador', 'bloqueio individual de empresa', 'empresa direta ou de grupo',
                           'negação individual', 'concessão individual', 'negação de grupo', 'concessão de grupo', 'negado por padrão']}


def company_access(conn, uid, cid):
    user = conn.execute('SELECT role,active FROM users WHERE id=?', (uid,)).fetchone()
    if not user or not user['active']:
        return False, ['Usuário desativado']
    if user['role'] == 'admin':
        return True, ['Administrador']
    direct = conn.execute('SELECT effect FROM user_company_access WHERE user_id=? AND company_id=?', (uid, cid)).fetchone()
    if direct and direct['effect'] == 'deny':
        return False, ['Bloqueio individual da empresa']
    origins = ['Concessão individual da empresa'] if direct else []
    if conn.execute('SELECT 1 FROM user_companies WHERE user_id=? AND company_id=?', (uid, cid)).fetchone():
        origins.append('Empresa atribuída ao usuário')
    origins.extend('Grupo: ' + r['name'] for r in conn.execute('''SELECT g.name FROM access_groups g
        JOIN group_users gu ON gu.group_id=g.id JOIN group_companies gc ON gc.group_id=g.id
        WHERE gu.user_id=? AND gc.company_id=? AND g.active=1 ORDER BY g.name''', (uid, cid)))
    return bool(origins), origins or ['Empresa não concedida']


def decision(conn, uid, cid, routine, action):
    allowed, company_origins = company_access(conn, uid, cid)
    if not allowed:
        return {'allowed': False, 'origin': company_origins[0], 'sources': company_origins}
    user = conn.execute('SELECT role FROM users WHERE id=?', (uid,)).fetchone()
    if user['role'] == 'admin':
        return {'allowed': True, 'origin': 'Administrador', 'sources': ['Administrador']}
    if routine == 'lookup':
        checks = [decision(conn,uid,cid,r,a) for r,a in [('system.companies','edit'),('fiscal.masters','read')]]
        return next((x for x in checks if x['allowed']),checks[0])
    if routine == 'dashboard':
        return {'allowed': True, 'origin': 'Empresa acessível', 'sources': company_origins}
    if routine not in ROUTINES or action not in ROUTINES[routine][1].split():
        return {'allowed': False, 'origin': 'Ação não definida', 'sources': []}
    patterns = ('*', routine.split('.')[0] + '.*', routine)
    entries = [dict(r) | {'origin': 'Permissão individual'} for r in conn.execute('''SELECT effect,routine,action
        FROM user_permissions WHERE user_id=? AND company_id=? AND routine IN (?,?,?) AND action IN ('*',?)''',
        (uid, cid, *patterns, action))]
    groups = [dict(r) | {'origin': 'Grupo: ' + r['name']} for r in conn.execute('''SELECT p.effect,p.routine,p.action,g.name
        FROM group_permissions p JOIN access_groups g ON g.id=p.group_id JOIN group_users u ON u.group_id=g.id
        JOIN group_companies c ON c.group_id=g.id AND c.company_id=p.company_id
        WHERE u.user_id=? AND p.company_id=? AND g.active=1 AND p.routine IN (?,?,?) AND p.action IN ('*',?)''',
        (uid, cid, *patterns, action))]
    for source, effect in ((entries, 'deny'), (entries, 'allow'), (groups, 'deny'), (groups, 'allow')):
        matching = [x for x in source if x['effect'] == effect]
        if matching:
            return {'allowed': effect == 'allow', 'origin': matching[0]['origin'],
                    'sources': [x['origin'] + ': ' + x['effect'] for x in entries + groups]}
    if routine.endswith('.periods') and action == 'read':
        prefix = routine.split('.')[0] + '.'
        if any(decision(conn,uid,cid,r,'read')['allowed'] for r in ROUTINES if r.startswith(prefix) and r != routine):
            return {'allowed':True,'origin':'Consulta do módulo','sources':['Consulta das competências acompanha a consulta de rotinas do módulo']}
    return {'allowed': False, 'origin': 'Sem concessão', 'sources': []}


def require(conn, uid, cid, routine=None, action='read', admin=False):
    from .core import DomainError
    user = conn.execute('SELECT role,active FROM users WHERE id=?', (uid,)).fetchone()
    if not user or not user['active']:
        raise DomainError('Acesso desativado.', 403, 'forbidden')
    if admin and user['role'] != 'admin':
        raise DomainError('Administração global reservada ao administrador.', 403, 'forbidden')
    if cid is None:
        return
    result = decision(conn, uid, cid, routine, action) if routine else {'allowed': company_access(conn, uid, cid)[0]}
    if not result['allowed']:
        label = ROUTINES.get(routine, (routine or 'empresa', ''))[0]
        raise DomainError(f'Sem permissão para {ACTIONS.get(action, action).lower()}: {label}, nesta empresa.', 403, 'forbidden')


def effect(conn, cid, routine, action):
    """Revalida efeitos indiretos dentro da mesma transação da operação principal."""
    from .db import request_context
    ctx = request_context.get()
    if ctx and ctx.get('user_id'):
        require(conn, ctx['user_id'], cid, routine, action)


def route_policy(path, method, query, payload, session):
    """Toda rota de dados recebe rotina/ação explícitas; novas rotas falham fechadas."""
    write = method not in {'GET', 'HEAD', 'OPTIONS'}
    action = {'POST': 'create', 'PUT': 'edit', 'PATCH': 'edit', 'DELETE': 'delete'}.get(method, 'read')
    if path in {'/api/context', '/api/logout', '/api/permissions/me', '/api/permissions/catalog'}:
        return None, None, False
    if re.match(r'^/api/(users|groups|access-audit|storage)(/|$)', path):
        return None, None, True
    if path == '/api/companies':
        return None, None, write
    if path.startswith('/api/lookups/'):
        return 'lookup', 'read', False
    if path == '/api/templates':
        return 'fiscal.parameters', action, False
    tail = re.sub(r'^/api/companies/\d+', '', path)
    if tail == '':
        return 'system.companies', action, False
    root = tail.strip('/').split('/')[0]
    if root == 'bulk-operations':
        # The stored preview owns the action. The service checks its permission
        # again inside the committing transaction; middleware still guards read,
        # session, CSRF, active company, module and exercise on both POSTs.
        routine = {'fiscal':'fiscal.documents','accounting':'accounting.journals'}.get(session.get('module'),'invalid')
        return routine, 'read', False
    if root == 'global-account-plans':
        if tail.endswith(('/original','/native')): return 'accounting.imports', 'export', False
        if tail.endswith('/publish'): return 'accounting.accounts', 'read', True
        if tail.endswith('/detach'): return 'accounting.accounts', 'edit', False
        if tail.endswith('/confirm'): return 'accounting.accounts', 'create', False
        return 'accounting.accounts', 'read', False
    if root == 'account-plans':
        if tail.endswith(('/export-preview','/export-confirm','/original','/native')):
            return 'accounting.imports', 'export', False
        if write:return 'accounting.imports', 'import', False
        return 'accounting.accounts', 'read', False
    if root == 'third-parties':
        return 'fiscal.masters', ('read' if not write or tail.endswith('/reuse-preview') else 'edit'), False
    if root == 'master-movements':
        return 'fiscal.documents', 'read', False
    if root == 'global-fiscal-catalogs':
        return 'fiscal.masters', action, write
    if root == 'fiscal-patterns':
        if tail.endswith('/preview'): return 'fiscal.parameters', 'read', False
        if tail.endswith('/apply'): return 'fiscal.parameters', 'create', False
        return 'fiscal.parameters', action, write
    if root == 'cfop-reference':
        return 'fiscal.masters', 'create' if write else 'read', False
    if root == 'cfop-source-loads':
        return 'fiscal.masters', 'read' if tail.endswith('/preview') or not write else 'create', False
    if root == 'fiscal-import-settings':
        return 'fiscal.parameters', 'edit' if write else 'read', False
    if root == 'fiscal-import-mappings':
        return 'fiscal.parameters', action, False
    mapping = {'accounts': 'accounting.accounts', 'cost-centers': 'accounting.cost_centers',
        'journals': 'accounting.journals', 'opening-balances': 'accounting.journals', 'documents': 'fiscal.documents',
        'titles': 'financial.titles', 'settlements': 'financial.settlements', 'renegotiations': 'financial.titles',
        'banks': 'financial.reconciliation', 'allocations': 'financial.reconciliation', 'partner-reconciliation': 'financial.reconciliation',
        'catalogs': 'fiscal.masters', 'rules': 'fiscal.parameters', 'templates': 'fiscal.parameters',
        'imports': 'fiscal.imports', 'assessments': 'fiscal.assessments', 'tax-adjustments': 'fiscal.assessments',
        'tax-ledgers': 'fiscal.assessments', 'fiscal-reports': 'fiscal.reports',
        'prosoft': 'accounting.prosoft', 'exports': 'accounting.prosoft', 'audit': 'system.audit'}
    if root == 'import-packages': return 'fiscal.imports', 'delete' if write else 'read', False
    if root == 'module-imports':
        module = payload.get('module') or query.get('module') or session.get('module')
        return module + '.imports' if module in {'accounting','financial'} else 'invalid', ('import' if write else 'export' if tail.endswith('/original') else 'read'), False
    if root == 'auditor':
        routine = 'auditor.catalogs' if '/catalogs' in tail else 'auditor.analyses'
        action = 'book' if tail.endswith('/publish') else 'edit' if tail.endswith(('/cancel','/restore','/treatment','/attachments')) else 'delete' if tail.endswith('/delete') else action
        if tail.endswith(('/import-preview','/reference')):action='import'
        if '/entries/' in tail and method=='DELETE':action='edit'
        if tail.endswith('/logs/export') or '/reports/' in tail:action='export'
        if tail.endswith('/original'):action='export'
        if tail.endswith(('/report','/files','/auxiliary')) or (not write and query.get('format','json') != 'json'):
            action = 'print' if tail.endswith('/report') and query.get('purpose') == 'print' and query.get('format','pdf') == 'pdf' else 'export'
        return routine, action, False
    if root == 'report-models':
        module = query.get('module') or session.get('module', 'accounting')
        return (module + '.reports' if module in {'fiscal', 'accounting', 'financial'} else 'invalid'), 'read', False
    if root == 'movement-exports':
        kind = tail.split('/')[2] if len(tail.split('/')) > 2 else ''
        routine = {'documents.xlsx': 'fiscal.documents', 'journals.xlsx': 'accounting.journals'}.get(kind, 'invalid')
        return routine, 'export', False
    if root == 'storage': return 'system.storage', 'export' if tail.endswith('/download') else 'read', False
    if root in {'exercises', 'periods'}:
        module = payload.get('module') or query.get('module') or session.get('module', 'fiscal')
        if module not in MODULES or module == 'system':
            return 'invalid', action, False
        action = 'close' if tail.endswith('/close') else 'reopen' if tail.endswith('/reopen') else action
        return module + '.periods', action, False
    if root == 'masters':
        kind = tail.split('/')[2] if len(tail.split('/')) > 2 else ''
        return ('accounting.histories' if kind in {'history', 'accounting_model'} else 'fiscal.masters'), action, False
    if root in {'business-reports', 'reports'}:
        kind = tail.split('/')[2] if len(tail.split('/')) > 2 else ''
        routine = 'financial.reports' if kind in {'financial', 'cash-flow', 'partners'} else 'fiscal.reports' if kind.startswith('fiscal-') else 'accounting.reports'
    elif root == 'dashboard':
        return 'dashboard', 'read', False
    else:
        routine = mapping.get(root, 'invalid')
    if root == 'imports':
        routine = 'financial.reconciliation' if session.get('module') == 'financial' else 'fiscal.imports'
        if write: action = 'import'
    if root == 'prosoft': action = 'export'
    if tail.endswith(('/original', '/download')): action = 'export'
    if tail.endswith('/review'): action = 'edit'
    if tail.endswith(('/book', '/finalize')): action = 'book'
    if tail.endswith('/settle'): routine, action = 'financial.settlements', 'settle'
    if tail.endswith(('/reverse', '/unreconcile')): action = 'reverse'
    if tail.endswith(('/allocate', '/reconcile', '/renegotiate')): action = 'edit'
    if not write and query.get('format', 'json') != 'json': action = 'print' if query.get('purpose') == 'print' and query.get('format') == 'pdf' else 'export'
    return routine, action, False


def import_access(conn,cid,parsed,action='read'):
    from .db import request_context
    ctx=request_context.get()
    if not ctx or not ctx.get('user_id'):return
    if parsed.get('documents'):require(conn,ctx['user_id'],cid,'fiscal.imports',action)
    if parsed.get('transactions'):require(conn,ctx['user_id'],cid,'financial.reconciliation',action)

def readable(conn,cid,routine):
    from .db import request_context
    ctx=request_context.get()
    return not ctx or not ctx.get('user_id') or decision(conn,ctx['user_id'],cid,routine,'read')['allowed']
