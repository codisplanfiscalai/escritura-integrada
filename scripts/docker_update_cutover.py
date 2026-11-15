"""Optional, explicitly enabled cold cutover. Never restores data or backups."""
from __future__ import annotations
import copy
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import time
import uuid
from urllib.parse import quote

from docker_update_executor import Refusal, packed, hashed, valid_digest, REPOSITORY

TERMINAL=('completed','recovered_previous','blocked')
HTTP_PROBE="import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3))))"


class LocalConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


class Engine:
    def __init__(self):
        connection=LocalConnection('localhost',timeout=10)
        try:
            connection.request('GET','/version')
            response=connection.getresponse();data=json.loads(response.read(65536))
            version=data.get('ApiVersion','')
            if response.status!=200 or not re.fullmatch(r'[0-9]+\.[0-9]+',version) or tuple(map(int,version.split('.')))<(1,45):
                raise Refusal('Docker Engine/API fora do escopo suportado.')
            self.version=version
        except (OSError,ValueError,http.client.HTTPException) as exc:
            raise Refusal('API local Docker indisponível.', 'engine_failed',503) from exc
        finally:connection.close()

    def request(self,method,path,payload=None,timeout=20,allow_missing=False):
        connection=LocalConnection('localhost',timeout=timeout)
        try:
            connection.request(method,'/v'+self.version+path,body=packed(payload).encode() if payload is not None else None,
                               headers={'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(2_000_001)
            if response.status==404 and allow_missing:return None
            if response.status>=300 or len(raw)>2_000_000:
                raise Refusal('Docker Engine não confirmou a operação; confira o job antes de intervir.', 'engine_failed',503)
            return json.loads(raw) if raw else {}
        except (OSError,ValueError,http.client.HTTPException) as exc:
            raise Refusal('Resposta do Docker Engine incerta. Recuperação/verificação administrativa necessária.', 'engine_uncertain',503) from exc
        finally:connection.close()

    def find(self,name):return self.request('GET','/containers/'+quote(name,safe='')+'/json',allow_missing=True)
    def inspect(self,cid):return self.request('GET','/containers/'+valid_id(cid)+'/json')
    def stop(self,cid):self.request('POST','/containers/'+valid_id(cid)+'/stop?t=-1',timeout=60)
    def start(self,cid):self.request('POST','/containers/'+valid_id(cid)+'/start')
    def rename(self,cid,name):self.request('POST','/containers/'+valid_id(cid)+'/rename?name='+quote(name,safe=''))
    def create(self,name,config):return self.request('POST','/containers/create?name='+quote(name,safe=''),config)['Id']


def valid_id(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
        raise Refusal('Identificador Docker inválido.')
    return value


class CutDocker:
    def __init__(self,docker,root,engine=None):
        self.docker,self.root,self._engine=docker,Path(root),engine

    @property
    def engine(self):
        if self._engine is None:self._engine=Engine()
        return self._engine

    def helper(self,image,action,job=None,data=None,backup=None):
        args=['run','--rm','--network','none','--read-only','--cap-drop','ALL',
              '--security-opt','no-new-privileges:true','--user','10001:10001',
              '--memory','512m','--pids-limit','64','--cpus','1',
              '--tmpfs','/tmp:rw,nosuid,noexec,size=134217728,uid=10001,gid=10001']
        if data:
            args+=['--mount',f'type=bind,source={self.docker.data_bind},target=/source,readonly']
        if backup:
            args+=['--name','escritura-update-backup-'+job,'--mount',f'type=bind,source={backup},target=/backup']
        args+=['--entrypoint','python',valid_digest(image),'-m','app.update_guard',action]
        if data:args+=['--data','/source']
        return json.loads(self.docker.run(args,timeout=600 if backup else 60))

    def exec(self,cid,action,job=None):
        args=['exec',valid_id(cid),'python','-m','app.update_guard',action]
        if job:args+=['--job-id',job]
        return json.loads(self.docker.run(args,timeout=60))

    def no_other_writers(self,allowed):
        ids=self.docker.run(['ps','--no-trunc','-q']).splitlines()
        bind=Path(self.docker.data_bind)
        for cid in ids:
            if cid in allowed:continue
            container=self.engine.inspect(cid)
            for mount in container.get('Mounts',[]):
                source=Path(mount.get('Source','/nonexistent'))
                if mount.get('Type')=='bind' and mount.get('RW') and (bind.is_relative_to(source) or source.is_relative_to(bind)):
                    raise Refusal('Outro container pode gravar no bind. Janela exclusiva não comprovada.', 'other_writer')

    def validate_config(self,container,target):
        cfg=container['Config'];host=container['HostConfig']
        if (cfg.get('Cmd')!=['python','scripts/run_container.py'] or cfg.get('Entrypoint')
                or cfg.get('User')!='10001:10001' or cfg.get('StopSignal') not in (None,'','SIGTERM','15') or cfg.get('Tty') or cfg.get('OpenStdin')
                or host.get('RestartPolicy',{}).get('Name','no') not in ('no','unless-stopped','')
                or host.get('AutoRemove') or host.get('VolumesFrom') or host.get('Privileged') or host.get('PublishAllPorts')
                or any(p.get('HostPort') in ('','0',None) for ports in (host.get('PortBindings') or {}).values() for p in (ports or []))
                or host.get('NetworkMode','').startswith(('host','container:'))
                or any(e in ('ESCRITURA_DEMO=1',) for e in cfg.get('Env',[]))
                or [e for e in cfg.get('Env',[]) if e.startswith('ESCRITURA_DATA_DIR=')]!=['ESCRITURA_DATA_DIR=/data']
                or any(m.get('RW') and m.get('Destination')!='/data' for m in container.get('Mounts',[]))):
            raise Refusal('Configuração fora do escopo do corte automático.', 'unsupported_configuration')
        for network in container['NetworkSettings']['Networks'].values():
            if network.get('IPAMConfig'):
                raise Refusal('IP estático exige procedimento administrativo separado.', 'unsupported_configuration')
        image=self.docker.image(target['image_id'])
        for field in ('User','Cmd','Entrypoint','Volumes','ExposedPorts','WorkingDir'):
            if (image['Config'].get(field) or None)!=(cfg.get(field) or None):
                raise Refusal('Defaults estruturais da imagem alvo diferem da instalação.', 'unsupported_configuration')
        if image['Id']!=target['image_id'] or REPOSITORY+'@'+target['digest'] not in image.get('RepoDigests',[]):
            raise Refusal('Cache do alvo não corresponde ao digest preparado.', 'invalid_image')
        result={**copy.deepcopy(cfg),'Image':target['image_id'],'HostConfig':copy.deepcopy(host)}
        if result['HostConfig'].get('OomKillDisable') is None:
            result['HostConfig']['OomKillDisable']=False  # Engine's equivalent default.
        labels=image['Config'].get('Labels',{})
        for key in set(result.get('Labels',{}))|set(labels):
            if key.startswith('org.opencontainers.image.') or key=='io.escritura.content-id':
                if key in labels:result['Labels'][key]=labels[key]
                else:result['Labels'].pop(key,None)
        result['NetworkingConfig']={'EndpointsConfig':{
            name:{k:copy.deepcopy(value[k]) for k in ('Aliases','Links','DriverOpts') if value.get(k) is not None}
            for name,value in container['NetworkSettings']['Networks'].items()}}
        return result

    @staticmethod
    def same_host(left,right):
        left,right=copy.deepcopy(left),copy.deepcopy(right)
        for value in (left,right):
            if value.get('OomKillDisable') is None:value['OomKillDisable']=False
        return left==right

    def same_configuration(self,container,expected):
        # Engine may normalize null/default fields. Everything represented by
        # inspect.Config/HostConfig must round-trip; no broad ignore list.
        if container['Config']!={k:v for k,v in expected.items() if k not in ('HostConfig','NetworkingConfig')}:
            raise Refusal('Configuração efetiva mudou durante a recriação.', 'configuration_changed')
        if not self.same_host(container['HostConfig'],expected['HostConfig']):
            raise Refusal('Opções/mounts/portas efetivos mudaram.', 'configuration_changed')
        wanted=expected['NetworkingConfig']['EndpointsConfig']
        actual=container['NetworkSettings']['Networks']
        if set(actual)!=set(wanted):raise Refusal('Redes efetivas divergentes.', 'configuration_changed')
        for name,value in wanted.items():
            for key,item in value.items():
                if key=='Aliases':
                    # Docker also records the current container ID/name alias.
                    if not set(item)<=set(actual[name].get(key) or []):raise Refusal('Aliases de rede divergentes.')
                elif (actual[name].get(key) or None)!=(item or None):raise Refusal('Configuração de rede divergente.')

    def health(self,cid,version,job,timeout=120):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            container=self.engine.inspect(cid)
            if not container['State'].get('Running'):
                raise Refusal('Aplicação alvo encerrou antes da confirmação de saúde.', 'health_failed')
            if container['State'].get('Health',{}).get('Status')=='healthy':
                try:
                    data=json.loads(self.docker.run(['exec',valid_id(cid),'python','-c',HTTP_PROBE],timeout=8))
                    if (data.get('status')=='ok' and data.get('version')==version
                            and data.get('update_protocol')==1 and data.get('update_hold')==job):return
                except (Refusal,ValueError):pass
            time.sleep(.5)
        raise Refusal('Healthcheck e HTTP/versão/manutenção não confirmados no prazo.', 'health_failed')

    def frozen_contract(self,cid,private):
        actual=self.helper(private['plan']['installed']['image_id'],'contract',data=True)
        if actual.get('held_job')!=cid or any(actual.get(k)!=private['source_contract'].get(k) for k in ('protocol','abi','schema')):
            raise Refusal('Manutenção ou esquema congelado mudou. Recuperação assistida necessária.','hold_changed')

    def original_unchanged(self,private):
        original=self.engine.inspect(private['old'])
        plan=private['plan']['installed']
        snapshot=private['container']
        if (original['Name'].lstrip('/') not in (private['name'],private['retained_name'])
                or original['Image']!=plan['image_id'] or original['Config']!=snapshot['Config']
                or not self.same_host(original['HostConfig'],snapshot['HostConfig'])
                or original['Mounts']!=snapshot['Mounts']):
            raise Refusal('Container/configuração original mudou externamente.','installed_changed')

    def stopped(self,cid):
        state=self.engine.inspect(cid)['State']
        if state.get('Running') or state.get('ExitCode')!=0 or state.get('OOMKilled'):
            raise Refusal('Encerramento limpo não comprovado. Não haverá SIGKILL/cópia/corte.', 'shutdown_unconfirmed')


class Cutovers:
    def __init__(self,executor,enabled=False,driver=None):
        self.executor=executor
        self.enabled=enabled
        self.driver=driver or CutDocker(executor.docker,Path(executor.ledger).parent)
        with executor.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS cutovers(
                id TEXT PRIMARY KEY, idem TEXT UNIQUE, prepared_id TEXT UNIQUE, state TEXT,
                public TEXT, private TEXT, created REAL, updated REAL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_cutover ON cutovers((1))
                  WHERE state NOT IN ('completed','recovered_previous','blocked');''')
            rows=db.execute("SELECT id,public FROM cutovers WHERE state NOT IN ('completed','recovered_previous','blocked','recovery_required')").fetchall()
            for cid,raw in rows:
                value=json.loads(raw);value['error']='Executor reiniciado: conferir manutenção/container; não há recuperação automática.'
                db.execute("UPDATE cutovers SET state='recovery_required',public=?,updated=? WHERE id=?",(packed(value),time.time(),cid))

    def busy(self):
        with self.executor.db() as db:
            return bool(db.execute("SELECT 1 FROM cutovers WHERE state NOT IN ('completed','recovered_previous','blocked')").fetchone())

    def list(self):
        with self.executor.db() as db:
            return [self.public(row) for row in db.execute('SELECT * FROM cutovers ORDER BY created DESC LIMIT 10')]

    def public(self,row):
        return {**json.loads(row[4]),'id':row[0],'state':row[3], 'created_at':row[6],'updated_at':row[7],
                'application_updated':row[3]=='completed'}

    def load(self,cid):
        with self.executor.db() as db:
            row=db.execute('SELECT * FROM cutovers WHERE id=?',(cid,)).fetchone()
        if not row:raise Refusal('Corte não encontrado.','not_found',404)
        return row,json.loads(row[4]),json.loads(row[5])

    def save(self,cid,state,public,private):
        with self.executor.db() as db:
            db.execute('UPDATE cutovers SET state=?,public=?,private=?,updated=? WHERE id=?',
                       (state,packed(public),packed(private),time.time(),cid))

    def begin(self,prepared_id,key,actor):
        if not self.enabled:raise Refusal('Corte não autorizado na configuração do host.','cutover_disabled',403)
        for value in (prepared_id,key):
            if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise Refusal('Identificador inválido.','invalid_request',422)
        with self.executor.lock,self.executor.db() as db:
            old=db.execute('SELECT * FROM cutovers WHERE idem=?',(key,)).fetchone()
            if old:
                if old[2]!=prepared_id or json.loads(old[4])['actor_id']!=actor:raise Refusal('Chave usada por outra intenção.')
                return self.public(old)
            old=db.execute('SELECT * FROM cutovers WHERE prepared_id=?',(prepared_id,)).fetchone()
            if old:return self.public(old)
            if self.busy() or db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','pulling','validating')").fetchone():
                raise Refusal('Operação ou recuperação em andamento.','operation_in_progress')
            if db.execute('SELECT count(*) FROM cutovers').fetchone()[0]>=100:raise Refusal('Limite de histórico de cortes atingido.')
            row=db.execute("SELECT payload FROM jobs WHERE id=? AND state='prepared'",(prepared_id,)).fetchone()
            if not row:raise Refusal('Prepare e confira a imagem primeiro.')
            plan=json.loads(row[0]);cid=uuid.uuid4().hex;stamp=time.time()
            public={'prepared_id':prepared_id,'actor_id':actor,'installed':plan['installed'],'target':plan['target'],'channel':plan['channel'],'error':None}
            private={'plan':plan,'released':False}
            db.execute('INSERT INTO cutovers VALUES(?,?,?,?,?,?,?,?)',(cid,key,prepared_id,'validating',packed(public),packed(private),stamp,stamp))
            db.commit();self.executor.pool.submit(self.work,cid)
            return self.public(db.execute('SELECT * FROM cutovers WHERE id=?',(cid,)).fetchone())

    def work(self,cid):
        _,public,private=self.load(cid);driver=self.driver;docker=self.executor.docker
        try:
            plan=private['plan'];old=plan['installed']['container_id'];target=plan['target']
            if docker.installed()!=plan['installed']:raise Refusal('Instalação mudou desde a preparação.')
            driver.no_other_writers({old});docker.space()
            container=driver.engine.inspect(old)
            expected=driver.validate_config(container,target)
            expected.setdefault('Labels',{})['io.escritura.update-job']=cid
            try:source_contract=driver.exec(old,'contract')
            except Refusal as exc:raise Refusal('Protocolo/integridade da origem não comprovados. Bootstrap administrativo necessário; nenhum container foi parado.','source_protocol') from exc
            source_template=driver.helper(plan['installed']['image_id'],'template')
            target_contract=driver.helper(target['image_id'],'template')
            if (source_contract.get('protocol')!=1 or source_contract.get('held_job') is not None or not source_contract.get('writable') or source_contract.get('abi')!=source_template.get('abi')
                    or any(source_template.get(k)!=target_contract.get(k) for k in ('protocol','abi','schema'))
                    or source_contract.get('version')!=plan['installed']['version'] or target_contract.get('version')!=target['version']):
                raise Refusal('Contrato de dados/esquema incompatível. Nenhuma migração será executada.','incompatible_schema')
            name=container['Name'].lstrip('/')
            if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.-]{0,199}',name):raise Refusal('Nome de container fora do escopo.')
            private.update(old=old,name=name,retained_name=name+'.previous-'+cid[:8],failed_name=name+'.failed-'+cid[:8],container=container,expected=expected,source_contract=source_contract)
            self.save(cid,'quiescing',public,private)
            held=driver.exec(old,'hold',cid)
            private['held']=True
            if held.get('job_id')!=cid or any(held.get(k)!=source_contract.get(k) for k in ('protocol','abi','schema')):
                raise Refusal('Contrato/dados da origem mudaram ao iniciar manutenção.')
            self.save(cid,'quiescing',public,private)
            driver.health(old,plan['installed']['version'],cid)
            # No timeout escalation: Engine stop?t=-1 never sends SIGKILL.
            private['stop_requested']=True;self.save(cid,'quiescing',public,private)
            driver.engine.stop(old);driver.stopped(old)
            driver.original_unchanged(private);driver.no_other_writers(set());driver.frozen_contract(cid,private)
            baseline=driver.helper(plan['installed']['image_id'],'inventory',data=True)
            private['baseline']=baseline;self.save(cid,'backup',public,private)
            destination=driver.root/'backups'/cid
            destination.parent.mkdir(mode=0o700,exist_ok=True)
            if shutil.disk_usage(destination.parent).free<baseline['bytes']*2+256*1024**2:
                raise Refusal('Espaço insuficiente para backup privado consistente.','backup_space')
            # Parent 0700 keeps this mount private. Helper UID 10001 writes only
            # this new empty destination, never source data or other backups.
            destination.mkdir(mode=0o777);destination.chmod(0o777)
            receipt=driver.helper(plan['installed']['image_id'],'backup',job=cid,data=True,backup=destination)
            if receipt['fingerprint']!=baseline['fingerprint']:raise Refusal('Backup diverge da origem.')
            public['backup']={k:receipt[k] for k in ('fingerprint','bytes','files','schema','sqlite_sha256')}
            driver.stopped(old);driver.original_unchanged(private);driver.no_other_writers(set())
            if driver.helper(plan['installed']['image_id'],'inventory',data=True)!=baseline:raise Refusal('Dados mudaram após backup.')
            private['creation_intent']=True;self.save(cid,'recreating',public,private)
            driver.engine.rename(old,private['retained_name'])
            new=driver.engine.create(name,expected)
            private['new']=valid_id(new);self.save(cid,'recreating',public,private)
            driver.same_configuration(driver.engine.inspect(new),expected)
            driver.frozen_contract(cid,private)
            driver.engine.start(new);self.save(cid,'healthcheck',public,private)
            driver.health(new,target['version'],cid)
            self.finish(cid,public,private)
        except Exception as exc:
            public['error']=exc.detail if isinstance(exc,Refusal) else 'Corte não confirmado. Confira o estado e use recuperação administrativa.'
            state='recovery_required' if private.get('old') else 'blocked'
            self.save(cid,state,public,private)

    def finish(self,cid,public,private):
        driver=self.driver;plan=private['plan'];new=private['new']
        container=driver.engine.inspect(new)
        if container['Name'].lstrip('/')!=private['name']:raise Refusal('Nome efetivo da aplicação mudou.')
        if container['Image']!=plan['target']['image_id']:raise Refusal('Imagem efetiva não corresponde ao alvo.')
        driver.same_configuration(container,private['expected']);driver.stopped(private['old']);driver.original_unchanged(private)
        driver.no_other_writers({new});driver.frozen_contract(cid,private)
        if driver.helper(plan['target']['image_id'],'inventory',data=True)!=private['baseline']:
            raise Refusal('Dados mudaram durante a verificação. Recuperação de imagem foi bloqueada.','data_changed')
        # Durable point of no automatic/old-image recovery. Removing hold can
        # immediately admit user/background writes, even if the next RPC fails.
        private['released']=True;private['release_destination']='target';self.save(cid,'releasing',public,private)
        driver.exec(new,'release',cid)
        driver.exec(new,'writable')
        driver.health(new,plan['target']['version'],None)
        public['error']=None;self.save(cid,'completed',public,private)

    def recover(self,cid,mode,actor):
        if not self.enabled:raise Refusal('Corte/recuperação não autorizado no host.','cutover_disabled',403)
        if not isinstance(cid,str) or not re.fullmatch('[a-f0-9]{32}',cid):raise Refusal('Identificador inválido.')
        with self.executor.lock:
            row,public,private=self.load(cid)
            if row[3]=='completed' and mode=='previous':
                raise Refusal('Escritas já foram liberadas no alvo. Retorno à imagem anterior proibido.','writes_released')
            if row[3]=='recovered_previous' and mode=='target':
                raise Refusal('Origem já retomada; outra atualização exige nova intenção.')
            if row[3]=='blocked':raise Refusal('Corte recusado; prepare uma nova intenção após corrigir a causa.')
            if row[3] in TERMINAL:return self.public(row)
            if row[3]!='recovery_required':raise Refusal('Aguarde a operação em andamento.')
            public['recovery_actor_id']=actor
            self.save(cid,'recovering',public,private)
            self.executor.pool.submit(self.recover_work,cid,mode)
            return {**self.public(row),'state':'recovering'}

    def recover_work(self,cid,mode):
        _,public,private=self.load(cid);driver=self.driver;plan=private['plan']
        try:
            if not private.get('new') and private.get('creation_intent'):
                found=driver.engine.find(private['name'])
                if found and found['Id']!=private['old']:
                    if found['Image']!=plan['target']['image_id'] or found['Config'].get('Labels',{}).get('io.escritura.update-job')!=cid:
                        raise Refusal('Nome ocupado por container alheio ao corte.')
                    driver.same_configuration(found,private['expected'])
                    private['new']=valid_id(found['Id']);self.save(cid,'recovering',public,private)
            if mode=='target':
                new=private.get('new')
                if not new:
                    if not private.get('creation_intent') or not public.get('backup') or private.get('released'):
                        raise Refusal('Alvo ainda não foi criado; retomada de criação não autorizada.')
                    driver.stopped(private['old']);driver.original_unchanged(private);driver.no_other_writers(set());driver.frozen_contract(cid,private)
                    if driver.helper(plan['installed']['image_id'],'inventory',data=True)!=private['baseline']:
                        raise Refusal('Dados mudaram; criação do alvo bloqueada.')
                    if driver.engine.inspect(private['old'])['Name'].lstrip('/')!=private['retained_name']:
                        driver.engine.rename(private['old'],private['retained_name'])
                    new=driver.engine.create(private['name'],private['expected'])
                    private['new']=valid_id(new);self.save(cid,'recovering',public,private)
                if private.get('released'):
                    if private.get('release_destination')!='target':raise Refusal('A imagem anterior já foi retomada; não haverá outro corte nesta recuperação.')
                    container=driver.engine.inspect(new)
                    driver.same_configuration(container,private['expected'])
                    if container['Image']!=plan['target']['image_id']:raise Refusal('Imagem alvo mudou.')
                    driver.no_other_writers({new})
                    self.finish_uncertain_release(cid,private,new,plan['target']['version'])
                    driver.health(new,plan['target']['version'],None);driver.exec(new,'writable')
                    # New writes are preserved. Never compare/restore old backup.
                    public['error']=None;self.save(cid,'completed',public,private)
                else:
                    driver.stopped(private['old']);driver.original_unchanged(private);driver.no_other_writers({new})
                    current=driver.engine.inspect(new)
                    if current['Image']!=plan['target']['image_id']:raise Refusal('Imagem efetiva do alvo mudou.')
                    driver.same_configuration(current,private['expected'])
                    if current['Name'].lstrip('/')!=private['name']:
                        if current['Name'].lstrip('/')!=private['failed_name']:raise Refusal('Nome do alvo mudou externamente.')
                        driver.engine.rename(new,private['name'])
                    driver.frozen_contract(cid,private)
                    if not current['State']['Running']:driver.engine.start(new)
                    driver.health(new,plan['target']['version'],cid)
                    self.finish(cid,public,private)
            elif mode=='previous':
                old=private['old'];new=private.get('new')
                driver.original_unchanged(private)
                if private.get('released'):
                    if private.get('release_destination')!='previous':raise Refusal('Escritas podem ter sido liberadas no alvo. Retorno à imagem anterior proibido.','writes_released')
                    driver.no_other_writers({old})
                    self.finish_uncertain_release(cid,private,old,plan['installed']['version'])
                    driver.health(old,plan['installed']['version'],None);driver.exec(old,'writable')
                    driver.no_other_writers({old})
                    self.save(cid,'recovered_previous',public,private)
                    return
                if not private.get('stop_requested'):
                    actual=driver.exec(old,'contract')
                    if actual.get('held_job') is None:
                        if self.executor.docker.installed()!=plan['installed']:raise Refusal('Instalação original mudou.')
                        public['error']='Manutenção não foi publicada; imagem original continua ativa.'
                        self.save(cid,'blocked',public,private)
                        return
                    if actual.get('held_job')!=cid or any(actual[k]!=private['source_contract'][k] for k in ('protocol','abi','schema')):
                        raise Refusal('Manutenção/contrato da origem não pertence a este corte.')
                    # Restart the same frozen image cleanly, including its workers.
                    private['stop_requested']=True;self.save(cid,'recovering',public,private)
                    driver.engine.stop(old);driver.stopped(old)
                if new:
                    candidate=driver.engine.inspect(new)
                    if candidate['Image']!=plan['target']['image_id']:raise Refusal('Alvo mudou externamente.')
                    if candidate['State']['Running']:driver.engine.stop(new)
                    state=driver.engine.inspect(new)['State']
                    if state['Running']:raise Refusal('Alvo não parou.')
                if private.get('old_start_intent') and driver.engine.inspect(old)['State']['Running']:
                    self.complete_previous(cid,public,private)
                    return
                driver.stopped(old);driver.no_other_writers(set())
                if not new and not private.get('baseline'):
                    existing=driver.helper(plan['installed']['image_id'],'contract',data=True)
                    if any(existing[k]!=private['source_contract'][k] for k in ('protocol','abi','schema')):
                        raise Refusal('Contrato original mudou; recuperação assistida necessária.')
                    current=None
                else:current=driver.helper(plan['installed']['image_id'],'inventory',data=True)
                if new and (not private.get('baseline') or current!=private['baseline']):
                    raise Refusal('Ausência/mudança do retrato de dados impede retorno da imagem.','data_changed')
                if not new and private.get('baseline') and current!=private['baseline']:
                    raise Refusal('Origem mudou durante a manutenção. Recuperação assistida necessária.','data_changed')
                if current is not None and not private.get('baseline'):private['baseline']=current
                # A stopped compatible image can restart against the exact same
                # frozen data. No copy-back, schema migration or restore exists.
                if new and driver.engine.inspect(new)['Name'].lstrip('/')!=private['failed_name']:
                    driver.engine.rename(new,private['failed_name'])
                if driver.engine.inspect(old)['Name'].lstrip('/')!=private['name']:
                    driver.engine.rename(old,private['name'])
                driver.frozen_contract(cid,private)
                private['old_start_intent']=True;self.save(cid,'recovering',public,private)
                driver.engine.start(old)
                self.complete_previous(cid,public,private)
            else:raise Refusal('Recuperação não suportada.')
        except Exception as exc:
            public['error']=exc.detail if isinstance(exc,Refusal) else 'Recuperação não confirmada; dados e backups foram preservados.'
            self.save(cid,'recovery_required',public,private)

    def finish_uncertain_release(self,cid,private,container,version):
        # The durable release intent is written before unlink. A lost response
        # may mean either an intact hold or new writes already admitted. Only
        # repeat unlink for our unchanged frozen hold; never compare/restore a
        # snapshot when the hold is absent and writes may have happened.
        driver=self.driver
        actual=driver.exec(container,'contract')
        if actual.get('held_job') is None:return
        if actual.get('held_job')!=cid:raise Refusal('Manutenção efetiva pertence a outra operação.')
        driver.frozen_contract(cid,private)
        if private.get('baseline') and driver.helper(private['plan']['installed']['image_id'],'inventory',data=True)!=private['baseline']:
            raise Refusal('Dados congelados mudaram; liberação pendente exige recuperação assistida.')
        driver.health(container,version,cid)
        driver.exec(container,'release',cid)

    def complete_previous(self,cid,public,private):
        driver=self.driver;plan=private['plan'];old=private['old']
        driver.original_unchanged(private);driver.frozen_contract(cid,private)
        driver.health(old,plan['installed']['version'],cid)
        driver.no_other_writers({old})
        if private.get('baseline') and driver.helper(plan['installed']['image_id'],'inventory',data=True)!=private['baseline']:
            raise Refusal('Dados mudaram na recuperação.')
        private['released']=True;private['release_destination']='previous'
        self.save(cid,'releasing_previous',public,private)
        driver.exec(old,'release',cid);driver.exec(old,'writable');driver.health(old,plan['installed']['version'],None)
        self.save(cid,'recovered_previous',public,private)
