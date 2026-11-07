"""Exercícios independentes e seleção de competência por sessão/empresa/módulo."""
from datetime import date
import json
from .core import DomainError, audit, company_row, digest, integer, now, period, text
from .permissions import MODULES, ROUTINES, company_access, decision, effect, require

BUSINESS_MODULES = ('fiscal', 'accounting', 'financial', 'social')


def initialize_exercises(conn, cid, year=None):
    for module in BUSINESS_MODULES:
        conn.execute('INSERT OR IGNORE INTO exercises VALUES(?,?,?,?,?)',
                     (cid,module,year or date.today().year,now(),'criação da empresa'))


def enabled(conn, cid, module, competence):
    return bool(conn.execute('SELECT 1 FROM exercises WHERE company_id=? AND module=? AND year=?',
                             (cid,module,int(competence[:4]))).fetchone())


def module_readable(conn, uid, cid, module):
    return any(decision(conn,uid,cid,r,'read')['allowed'] for r in ROUTINES if r.startswith(module + '.'))


class PeriodMixin:
    def session(self, token):
        result = super().session(token)
        if not result['authenticated']: return result | {'module': 'fiscal', 'permissions': {}, 'available_modules': []}
        with self.db.read() as conn:
            row = conn.execute('SELECT module FROM sessions WHERE token_hash=?', (digest(token.encode()),)).fetchone()
            result['module'] = row['module'] if row else 'fiscal'
            result['year'] = int(result['period'][:4])
            cid, uid = result['active_company_id'], result['user']['id']
            result['permissions'] = {r:[a for a in actions.split() if decision(conn,uid,cid,r,a)['allowed']]
                                     for r,(_,actions) in ROUTINES.items()} if cid else {}
            result['available_modules'] = [m for m in (*BUSINESS_MODULES, 'auditor') if cid and module_readable(conn,uid,cid,m)]
        return result

    def context(self, token, payload):
        cid = integer(payload.get('company_id'), 'Empresa')
        token_hash = digest(token.encode())
        with self.db.transaction() as conn:
            company_row(conn,cid)
            session = conn.execute('SELECT * FROM sessions WHERE token_hash=?', (token_hash,)).fetchone()
            if not session: raise DomainError('Entre novamente.',401,'unauthenticated')
            require(conn,session['user_id'],cid)
            module = payload.get('module',session['module'])
            if module not in (*BUSINESS_MODULES, 'auditor'): raise DomainError('Módulo de competência inválido.')
            if not module_readable(conn,session['user_id'],cid,module):
                if payload.get('module'): raise DomainError('Sem acesso ao módulo nesta empresa.',403,'forbidden')
                module = next((m for m in (*BUSINESS_MODULES, 'auditor') if module_readable(conn,session['user_id'],cid,m)),None)
                if not module: raise DomainError('Nenhum módulo de trabalho concedido nesta empresa.',403,'forbidden')
            saved = conn.execute('SELECT period FROM session_contexts WHERE token_hash=? AND company_id=? AND module=?', (token_hash,cid,module)).fetchone()
            competence = period(payload.get('period') or (saved['period'] if saved else session['period']))
            if module != 'auditor' and not enabled(conn,cid,module,competence):
                if payload.get('period'):
                    raise DomainError('Exercício ainda não cadastrado neste módulo. Abra Competências e cadastre o ano.',409,'exercise_missing')
                latest = conn.execute('SELECT year FROM exercises WHERE company_id=? AND module=? ORDER BY year DESC LIMIT 1',(cid,module)).fetchone()
                if not latest: raise DomainError('Cadastre um exercício para este módulo.',409,'exercise_missing')
                competence = f"{latest['year']:04d}-01"
            conn.execute('UPDATE sessions SET active_company_id=?,period=?,module=? WHERE token_hash=?',(cid,competence,module,token_hash))
            conn.execute('INSERT INTO session_contexts VALUES(?,?,?,?) ON CONFLICT(token_hash,company_id,module) DO UPDATE SET period=excluded.period',(token_hash,cid,module,competence))
        return self.session(token)

    def _periods(self,conn,cid,competence):
        result={'period':competence}
        for module in BUSINESS_MODULES:
            row=conn.execute('SELECT * FROM period_locks WHERE company_id=? AND period=? AND module=?',(cid,competence,module)).fetchone()
            item=dict(row) if row else {'module':module,'period':competence,'closed':False,'reason':'','version':0,'actor':'','changed_at':None}
            item['closed']=bool(item['closed']);item['enabled']=enabled(conn,cid,module,competence)
            item['status']='closed' if item['closed'] else 'open' if item['enabled'] else 'unavailable'
            result[module]=item
        return result

    def exercises(self,cid,module,year=None):
        if module not in BUSINESS_MODULES:raise DomainError('Módulo inválido.')
        with self.db.read(snapshot=True) as conn:
            company_row(conn,cid)
            years=[dict(r) for r in conn.execute('SELECT * FROM exercises WHERE company_id=? AND module=? ORDER BY year DESC',(cid,module))]
            selected=integer(year,'Exercício',1900) if year else (years[0]['year'] if years else date.today().year)
            if selected>2199:raise DomainError('Exercício deve estar entre 1900 e 2199.')
            return {'company_id':cid,'module':module,'year':selected,'years':years,
                    'months':[self._periods(conn,cid,f'{selected:04d}-{m:02d}')[module] for m in range(1,13)]}

    def create_exercise(self,cid,payload,actor):
        module=payload.get('module');year=integer(payload.get('year'),'Exercício',1900)
        if module not in BUSINESS_MODULES or year>2199:raise DomainError('Informe módulo e exercício de 1900 a 2199.')
        with self.db.transaction() as conn:
            company_row(conn,cid);effect(conn,cid,module+'.periods','create')
            old=conn.execute('SELECT 1 FROM exercises WHERE company_id=? AND module=? AND year=?',(cid,module,year)).fetchone()
            if not old:
                conn.execute('INSERT INTO exercises VALUES(?,?,?,?,?)',(cid,module,year,now(),actor))
                audit(conn,cid,actor,'create','exercise',f'{module}:{year}',{'module':module,'year':year,'months':12})
        return self.exercises(cid,module,year)

    def set_period(self,cid,payload,actor,closed):
        competence=period(payload.get('period'));module=payload.get('module')
        reason=text(payload.get('reason'),'Justificativa',True,1000)
        if module not in BUSINESS_MODULES:raise DomainError('Módulo inválido.')
        with self.db.transaction() as conn:
            company_row(conn,cid);effect(conn,cid,module+'.periods','close' if closed else 'reopen')
            if not enabled(conn,cid,module,competence):raise DomainError('Cadastre o exercício antes de fechar ou reabrir.',409,'exercise_missing')
            current=self._periods(conn,cid,competence)[module]
            if payload.get('version') is not None and payload['version']!=current['version']:
                raise DomainError('Situação alterada por outro usuário. Atualize a competência.',409,'stale_version')
            if current['closed']==closed:raise DomainError('A competência já está nesse estado.',409,'period_state_conflict')
            if closed and module=='fiscal':
                count=conn.execute("SELECT COUNT(*) FROM documents WHERE company_id=? AND period=? AND status<>'booked'",(cid,competence)).fetchone()[0]
                if count:raise DomainError(f'Há {count} documento(s) sem escrituração concluída.',409,'pending_documents')
            if closed and module=='accounting':
                bad=conn.execute('''SELECT j.id FROM journals j LEFT JOIN journal_lines l ON l.journal_id=j.id
                    WHERE j.company_id=? AND j.period=? GROUP BY j.id HAVING COALESCE(SUM(l.debit_cents),0)<>COALESCE(SUM(l.credit_cents),0)
                    OR COALESCE(SUM(l.debit_cents),0)=0 LIMIT 1''',(cid,competence)).fetchone()
                if bad:raise DomainError('Existem partidas inconsistentes.',409,'unbalanced_journal')
            conn.execute('''INSERT INTO period_locks VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(company_id,period,module)
                DO UPDATE SET closed=excluded.closed,reason=excluded.reason,actor=excluded.actor,changed_at=excluded.changed_at,version=period_locks.version+1''',
                (cid,competence,module,closed,reason,actor,now()))
            audit(conn,cid,actor,'close' if closed else 'reopen','period',competence+':'+module,{'module':module,'reason':reason,'previous_version':current['version']})
            return self._periods(conn,cid,competence)
