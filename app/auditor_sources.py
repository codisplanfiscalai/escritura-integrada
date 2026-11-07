"""Recupera XMLs dos contêineres originais sem alterar os importadores fiscais."""
import io
from pathlib import PurePosixPath
from zipfile import ZipFile
from .core import DomainError


def original_xmls(filename,raw,depth=0,state=None):
    state=state or {'members':0,'expanded':0}
    suffix=PurePosixPath(filename.lower()).suffix
    if suffix=='.xml':return [(filename,raw)]
    if suffix not in {'.zip','.7z','.rar'}:return []
    if depth>=2:raise DomainError('Origem excede dois níveis de compactação.')
    if suffix=='.zip':
        from .auditor import members
        # Mesmo validador de caminhos; tipos adicionais não são executados.
        with ZipFile(io.BytesIO(raw)) as z:
            entries=z.infolist();children=[]
            if state['members']+len(entries)>1000:raise DomainError('Origem excede 1.000 membros.')
            state['members']+=len(entries)
            for e in entries:
                path=PurePosixPath(e.filename.replace('\\','/'))
                if path.is_absolute() or '..' in path.parts or ':' in e.filename or e.flag_bits&1 or (e.external_attr>>16)&0o170000==0o120000:raise DomainError('Caminho inseguro na origem.')
                if e.is_dir():continue
                if e.file_size>20*1024*1024 or state['expanded']+e.file_size>100*1024*1024 or e.file_size/max(e.compress_size,1)>500:raise DomainError('Origem excede limite de expansão.')
                state['expanded']+=e.file_size
                children.append((e.filename,z.read(e)))
    else:
        from .archives import read_archive
        children=read_archive(suffix[1:],raw,state,(20*1024*1024,100*1024*1024,1000,500))
        state['expanded']+=sum(len(r) for _,r in children)
    return [(name,data) for name,content in children for name,data in original_xmls(name,content,depth+1,state)]
