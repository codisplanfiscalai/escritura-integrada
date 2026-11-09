"""Prévia XLSX derivada do normalizador do Auditor 1.2.2 (MIT).

Não presume que códigos sintaticamente válidos constem de uma tabela vigente.
Linhas hierárquicas, fórmulas e conflitos permanecem no diagnóstico da origem.
"""
import io
import re
from zipfile import ZipFile, BadZipFile
from openpyxl import load_workbook
from .core import DomainError


def normalize_xlsx(raw):
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist()
            if len(entries)>2000 or sum(e.file_size for e in entries)>100*1024*1024:
                raise DomainError('Planilha excede o limite de expansão.')
            if any(e.flag_bits&1 or e.file_size/max(e.compress_size,1)>500 for e in entries):
                raise DomainError('Planilha criptografada ou com expansão excessiva.')
        book=load_workbook(io.BytesIO(raw),read_only=True,data_only=False,keep_links=False)
    except (BadZipFile,ValueError,KeyError):raise DomainError('Arquivo XLSX inválido.')
    try:
        sheet=book['Tabela Completa'] if 'Tabela Completa' in book.sheetnames else book.worksheets[0]
        if sheet.max_column>100:raise DomainError('Planilha excede 100 colunas.')
        iterator=sheet.iter_rows(values_only=True);header=[str(x or '').strip() for x in next(iterator,[])]
        aliases={'ncm':['NCM'],'ex_code':['EX'],'description':['DESCRIÇÃO','Descrição'],'cst':['CST IBS/CBS','CST'],'cclass_trib':['cClassTrib'],'reduction_type':['Tipo_Redução'],'legal_reference':['LC214_Codigo_raw']}
        indices={key:next((header.index(a) for a in names if a in header),None) for key,names in aliases.items()}
        if any(indices[key] is None for key in ('ncm','description','cst','cclass_trib')):
            raise DomainError('Colunas obrigatórias: NCM; DESCRIÇÃO; CST IBS/CBS; cClassTrib.')
        result=[];issues=[];previous='';count=0;keys={}
        def issue(row,code,message):issues.append({'source_row':row,'code':code,'message':message})
        for n,values in enumerate(iterator,2):
            if n>25001:raise DomainError('Limite de 25.000 linhas.')
            if not any(v is not None for v in values):continue
            count+=1
            def cell(key):
                idx=indices[key];v=values[idx] if idx is not None and idx<len(values) else ''
                return str(v if v is not None else '').strip()
            if any(cell(k).startswith('=') for k in indices):
                issue(n,'FORMULA','Converta fórmulas em valores e confira a origem.');continue
            ncm=cell('ncm');ex=cell('ex_code');inherited=False
            if ncm:previous=ncm
            elif ex and previous:ncm=previous;inherited=True
            nd=ncm.replace('.','')
            if not re.fullmatch(r'[0-9]{8}',nd):
                issue(n,'NCM_HIERARCHY_OR_INVALID','Linha hierárquica ou NCM sem oito dígitos: não será aplicada a itens.');continue
            cst=cell('cst');cc=cell('cclass_trib')
            if cst.isascii() and cst.isdigit():cst=cst.zfill(3)
            if cc.isascii() and cc.isdigit():cc=cc.zfill(6)
            if not re.fullmatch(r'[0-9]{3}',cst) or not re.fullmatch(r'[0-9]{6}',cc) or not cc.startswith(cst):
                issue(n,'CLASSIFICATION_INVALID','CST/cClassTrib ausente, inválido ou incompatível.');continue
            if ex and not re.fullmatch(r'[0-9]{1,3}',ex):
                issue(n,'EX_INVALID','EX deve conter de um a três dígitos.');continue
            ex=ex.zfill(2) if ex else ''
            row={'ncm':nd,'ex_code':ex,'cst':cst,'cclass_trib':cc,'description':cell('description'),'source_row':n,'source_sheet':sheet.title,'inherited_ncm':inherited,'reduction_type':cell('reduction_type'),'legal_reference':cell('legal_reference')}
            key=(nd,ex)
            if key in keys:
                issue(n,'NCM_EX_DUPLICATE','NCM/EX repetido; revise todas as ocorrências antes de publicar.')
                issue(keys[key]['source_row'],'NCM_EX_DUPLICATE','Outra linha repete este NCM/EX.');keys[key]['conflict']=True;continue
            keys[key]=row;result.append(row)
            if row['reduction_type'] or row['legal_reference']:
                issue(n,'NORMATIVE_REVIEW','Condição/redução/base legal preservada como referência; revisão fiscal necessária, sem aplicação automática de alíquota.')
        accepted=[r for r in result if not r.get('conflict')]
        return {'entries':accepted,'issues':issues,'source_sheet':sheet.title,'rows':count,'eligible':len(accepted),'excluded':count-len(accepted),'coverage':'Validação estrutural. Existência e vigência na tabela oficial exigem revisão da fonte.'}
    finally:book.close()
