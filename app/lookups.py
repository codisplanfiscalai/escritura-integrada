"""Consultas assistidas com endpoints fixos, cache persistido e limites globais."""
import json
import os
import re
import time
import urllib.error
import urllib.request
from .core import DomainError, normalize_cnpj, now, pack, text

PROVIDERS = {
    'cnpjws': {'kind':'cnpj','url':'https://publica.cnpj.ws/cnpj/{}','limit':3},
    'receitaws': {'kind':'cnpj','url':'https://www.receitaws.com.br/v1/cnpj/{}','limit':3},
    'brasilapi': {'kind':'cnpj','url':'https://brasilapi.com.br/api/cnpj/v1/{}','limit':3},
    'viacep': {'kind':'cep','url':'https://viacep.com.br/ws/{}/json/','limit':30},
    'brasilapi_cep': {'kind':'cep','url':'https://brasilapi.com.br/api/cep/v2/{}','limit':30},
}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(url, headers, timeout):
    req = urllib.request.Request(url, headers={'Accept':'application/json','User-Agent':'EscrituraIntegrada/1.0',**headers})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('Resposta excede o limite')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Resposta inválida')
    return data


def _s(v):
    return '' if v is None else str(v)


def normalize(provider, data, query):
    if provider in {'viacep','brasilapi_cep'}:
        if data.get('erro') in (True,'true'):
            raise DomainError('CEP não localizado.',404,'not_found')
        return {'postal_code':query,'address':_s(data.get('logradouro',data.get('street'))),
                'district':_s(data.get('bairro',data.get('neighborhood'))),
                'city':_s(data.get('localidade',data.get('city'))),'state':_s(data.get('uf',data.get('state'))),
                'ibge':_s(data.get('ibge',{}).get('city') if isinstance(data.get('ibge'),dict) else data.get('ibge')), 'profile':{'complement':_s(data.get('complemento'))}}
    if data.get('status') == 'ERROR':
        raise DomainError('CNPJ não localizado pelo provedor.',404,'not_found')
    profile = {'ie_status':'unknown','state_registrations':[],'secondary_cnaes':[]}
    if provider == 'cnpjws':
        e = data.get('estabelecimento') or {}
        if not e or _s(e.get('cnpj')) != query:
            raise ValueError('Identidade diferente da consulta')
        regs = e.get('inscricoes_estaduais')
        if isinstance(regs,list):
            profile['ie_status'] = 'registered' if regs else 'not_found'
            profile['state_registrations'] = [{'state':(x.get('estado') or {}).get('sigla',''),
                'number':_s(x.get('inscricao_estadual')), 'active':x.get('ativo'),
                'updated_at':_s(x.get('atualizado_em')),'source':provider} for x in regs if x.get('inscricao_estadual')]
        profile.update(legal_nature=_s((data.get('natureza_juridica') or {}).get('id')),
            registration_status=_s(e.get('situacao_cadastral')),complement=_s(e.get('complemento')),
            secondary_cnaes=[_s(x.get('id')).zfill(7) for x in e.get('atividades_secundarias',[]) if x.get('id')])
        out = {'name':_s(data.get('razao_social')),'trade_name':_s(e.get('nome_fantasia')),
            'address':' '.join(filter(None,[_s(e.get('tipo_logradouro')),_s(e.get('logradouro'))])),
            'number':_s(e.get('numero')),'district':_s(e.get('bairro')),'postal_code':_s(e.get('cep')),
            'city':_s((e.get('cidade') or {}).get('nome')),'ibge':_s((e.get('cidade') or {}).get('ibge_id')),
            'state':_s((e.get('estado') or {}).get('sigla')),'email':_s(e.get('email')),
            'phone':_s(e.get('ddd1'))+_s(e.get('telefone1')),'cnae':(_s((e.get('atividade_principal') or {}).get('id')).zfill(7) if (e.get('atividade_principal') or {}).get('id') else '')}
    else:
        returned = re.sub(r'\D','',_s(data.get('cnpj')))
        if returned != query:
            raise ValueError('Identidade diferente da consulta')
        receita = provider == 'receitaws'
        cnae = ((data.get('atividade_principal') or [{}])[0].get('code') if receita else data.get('cnae_fiscal'))
        out = {'name':_s(data.get('nome' if receita else 'razao_social')),'trade_name':_s(data.get('fantasia' if receita else 'nome_fantasia')),
            'address':_s(data.get('logradouro')),'number':_s(data.get('numero')),'district':_s(data.get('bairro')),
            'postal_code':re.sub(r'\D','',_s(data.get('cep'))),'city':_s(data.get('municipio')),'state':_s(data.get('uf')),
            'ibge':_s(data.get('codigo_municipio_ibge')),'email':_s(data.get('email')),
            'phone':_s(data.get('telefone' if receita else 'ddd_telefone_1')),'cnae':(re.sub(r'\D','',_s(cnae)).zfill(7) if cnae else '')}
        profile.update(legal_nature=_s(data.get('natureza_juridica')),registration_status=_s(data.get('situacao' if receita else 'descricao_situacao_cadastral')),
                       complement=_s(data.get('complemento')),
                       secondary_cnaes=[re.sub(r'\D','',_s(x.get('code' if receita else 'codigo'))).zfill(7) for x in data.get('atividades_secundarias' if receita else 'cnaes_secundarios',[]) if x.get('code' if receita else 'codigo')])
    if not out['name']:
        raise ValueError('Razão social ausente')
    out.update(tax_id=query,profile=profile)
    # No single IE is picked automatically; multiple states require operator review.
    return out


class LookupService:
    def __init__(self, db, transport=fetch_json, clock=time.time):
        self.db, self.transport, self.clock = db, transport, clock

    def _reserve(self, provider, limit):
        stamp = self.clock()
        with self.db.transaction() as conn:
            row = conn.execute('SELECT * FROM lookup_limits WHERE provider=?',(provider,)).fetchone()
            if row and row['blocked_until'] > stamp:
                return False
            start = row['window_start'] if row and stamp-row['window_start'] < 60 else stamp
            count = row['count'] if row and start==row['window_start'] else 0
            if count >= limit:
                return False
            conn.execute('INSERT INTO lookup_limits(provider,window_start,count,blocked_until) VALUES(?,?,?,0) ON CONFLICT(provider) DO UPDATE SET window_start=excluded.window_start,count=excluded.count', (provider,start,count+1))
            return True

    def query(self, kind, value, provider='auto', refresh=False):
        value = text(value,'CNPJ/CEP',True,30)
        if kind == 'cnpj':
            value = normalize_cnpj(value)
            if not value.isdigit():
                raise DomainError('CNPJ alfanumérico: cadastro manual disponível; os provedores configurados ainda não têm contrato confirmado para esta variante.',422,'provider_unsupported')
            order = ['cnpjws','receitaws','brasilapi']
        elif kind == 'cep':
            value = re.sub(r'[.\- ]','',value)
            if not re.fullmatch(r'\d{8}',value):
                raise DomainError('CEP deve conter oito dígitos.')
            order = ['viacep','brasilapi_cep']
        else:
            raise DomainError('Tipo de consulta inválido.')
        if provider != 'auto':
            if provider not in order:
                raise DomainError('Provedor incompatível com a consulta.')
            order = [provider]
        stale = None
        with self.db.read() as conn:
            cached = {r['provider']:dict(r) for r in conn.execute('SELECT * FROM lookup_cache WHERE kind=? AND query=?',(kind,value))}
        for p in order:
            r = cached.get(p)
            if r and r['expires_at'] > self.clock() and not refresh:
                return self._result(r,True,False)
            if r and (not stale or r['fetched_at'] > stale['fetched_at']):
                stale = r
        attempts = []
        for p in order:
            spec = PROVIDERS[p]
            if not self._reserve(p,spec['limit']):
                attempts.append({'provider':p,'status':'rate_limited'}); continue
            try:
                url, headers = spec['url'].format(value), {}
                token = os.environ.get('ESCRITURA_CNPJWS_TOKEN','')
                if p=='cnpjws' and token:
                    url='https://comercial.cnpj.ws/cnpj/'+value;headers={'x_api_token':token}
                data = self.transport(url,headers,4)
                fields = normalize(p,data,value)
                stamp = now()
                fields.setdefault('profile',{}).update(lookup_source=p,lookup_date=stamp)
                item = {'provider':p,'kind':kind,'query':value,'data_json':pack(fields),'fetched_at':stamp,'expires_at':self.clock()+86400}
                with self.db.transaction() as conn:
                    conn.execute('INSERT INTO lookup_cache(kind,query,provider,data_json,fetched_at,expires_at) VALUES(?,?,?,?,?,?) ON CONFLICT(kind,query,provider) DO UPDATE SET data_json=excluded.data_json,fetched_at=excluded.fetched_at,expires_at=excluded.expires_at',
                        (kind,value,p,item['data_json'],stamp,item['expires_at']))
                return self._result(item,False,False) | {'attempts':attempts}
            except urllib.error.HTTPError as e:
                status = 'not_found' if e.code==404 else 'rate_limited' if e.code==429 else 'unavailable'
                if e.code==429:
                    try: wait=min(max(int(e.headers.get('Retry-After','60')),60),86400)
                    except (ValueError,TypeError): wait=60
                    with self.db.transaction() as conn:
                        conn.execute('UPDATE lookup_limits SET blocked_until=? WHERE provider=?',(self.clock()+wait,p))
                attempts.append({'provider':p,'status':status})
            except DomainError as e:
                attempts.append({'provider':p,'status':e.code})
            except (OSError,ValueError,TypeError,KeyError,AttributeError):
                attempts.append({'provider':p,'status':'unavailable'})
        if stale:
            return self._result(stale,True,True) | {'attempts':attempts}
        return {'kind':kind,'query':value,'fields':{},'provider':None,'fetched_at':None,'cached':False,'stale':False,
                'status':'unavailable','attempts':attempts,'message':'Consulta indisponível ou sem resultado. O cadastro manual continua disponível.'}

    @staticmethod
    def _result(r,cached,stale):
        return {'kind':r['kind'],'query':r['query'],'provider':r['provider'],'fields':json.loads(r['data_json']),
                'fetched_at':r['fetched_at'],'cached':cached,'stale':stale,'status':'ok',
                'message':'Dados anteriores: a atualização está indisponível.' if stale else 'Revise os campos antes de aplicar. A consulta não comprova enquadramento tributário ou isenção de IE.'}
