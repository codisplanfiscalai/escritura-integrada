"""Local reception -> one canonical import batch. No fiscal network is used."""
import base64
import io
import zipfile
from .core import DomainError, company_row, digest, iso_date, period
from .permissions import require
from .reception_workspace import ReceptionWorkspace
from .reception_archive import select


def prepare(core,reception,cid,uid,actor,provider,payload):
    allowed={'period','environment','posting_date','documents','filters'}
    if not isinstance(payload,dict) or set(payload)-allowed or ('documents' in payload)==('filters' in payload):
        raise DomainError('Informe seleção ou filtros, ambiente, competência e data de escrituração.')
    competence=period(payload.get('period')); day=iso_date(payload.get('posting_date'),'Escrituração')
    if day[:7]!=competence: raise DomainError('Data de escrituração fora da competência selecionada.')
    environment=payload.get('environment');reception._spec(provider,environment)
    with core.db.read(snapshot=True) as conn:
        require(conn,uid,cid,'fiscal.imports','import')
        require(conn,uid,cid,'fiscal.documents','book')
        company=company_row(conn,cid)
        if 'filters' in payload:
            f=payload['filters']
            if not isinstance(f,dict) or set(f)-{'query','direction','competence'}: raise DomainError('Filtros do acervo inválidos.')
            w=ReceptionWorkspace(core,reception)
            w.validate_filters(provider,environment,int(competence[:4]),f.get('query',''),0,f.get('direction',''),f.get('competence',''))
            # Acquisition year is not the XML's fiscal competence. Search all
            # local receipt years and apply the user's explicit XML filter.
            groups=w.archive(conn,cid,provider,environment,company['tax_id'])
            documents=[item for group in groups if (item:=select(group,None,f.get('query',''),f.get('direction',''),f.get('competence',''))) is not None]
            if any(d.get('versions_pending_review') for d in documents):
                raise DomainError('Há XMLs com versões diferentes. Confira as origens e selecione os documentos explicitamente.',409,'reception_version_review')
            documents=[{'receipt_key':d['receipt_key'],'nsu':d['nsu']} for d in documents if d.get('document_type')=='NFSE' or d.get('kind')=='full_xml']
        else: documents=payload['documents']
    if not isinstance(documents,list) or not 1<=len(documents)<=1000:
        raise DomainError('Selecione de 1 a 1.000 XMLs completos; refine os filtros para lotes maiores.')
    files={};seen=set();sources=[]
    for row in documents:
        if not isinstance(row,dict) or set(row)-{'receipt_key','nsu'}: raise DomainError('Seleção de documento inválida.')
        key=row.get('receipt_key');metadata,raw=reception.document(cid,key,row.get('nsu'),uid)
        receipt=reception.receipt(cid,key,uid)
        if receipt.get('provider')!=provider or receipt.get('environment')!=environment or receipt.get('target_tax_id')!=company['tax_id']:
            raise DomainError('Documento de outro serviço, ambiente ou inscrição.',409,'reception_source_mismatch')
        if metadata.get('document_type')!='NFSE' and metadata.get('kind')!='full_xml':
            raise DomainError('Resumo ou evento não pode ser escriturado como nota.',409,'reception_not_full_xml')
        sha=digest(raw)
        if sha in seen: continue
        seen.add(sha);name='documento-'+sha+'.xml';files[name]=raw
        sources.append({'receipt_key':key,'nsu':metadata['nsu'],'sha256':sha})
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
        for name,raw in sorted(files.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));archive.writestr(info,raw)
    raw=stream.getvalue()
    # Reuse parser limits, canonical original storage, review and transactional
    # confirmation. This operation prepares a batch; it never books implicitly.
    batch=core.preview_import(cid,{'filename':'recepcao-'+provider+'-'+digest(raw)[:20]+'.zip',
        'period':competence,'options':{'posting_date':day,'reception_provider':provider,'reception_environment':environment},'content_base64':base64.b64encode(raw).decode()},actor)
    return {'import_id':batch['id'],'period':competence,'documents':len(files),'sources':sources,'batch':batch}
