"""Leitura limitada de 7z/RAR sem extrair membros para o sistema de arquivos."""
import io
import os
import re
import shutil
from pathlib import PurePosixPath


def read_archive(kind,data,state,limits):
    # Lazy imports keep unsupported codecs from breaking the application startup.
    from .importers import ImportProblem
    file_limit,total_limit,member_limit,ratio=limits
    def validate(entries):
        state['members']+=len(entries)
        if state['members']>member_limit:raise ImportProblem('ARCHIVE_MEMBERS','Quantidade de membros excede o limite do lote.')
        seen=set();total=0
        for name,size,isdir,isfile in entries:
            normalized=name.replace('\\','/');path=PurePosixPath(normalized)
            if '\x00' in normalized or path.is_absolute() or '..' in path.parts or ':' in normalized or (not isdir and not isfile):
                raise ImportProblem('ARCHIVE_UNSAFE_PATH','Pacote contém caminho inseguro, link ou tipo de arquivo não regular.')
            if normalized in seen:raise ImportProblem('ARCHIVE_DUPLICATE_NAME','Membros repetidos tornam a origem ambígua.')
            seen.add(normalized)
            if not isdir:
                if size<0 or size>file_limit:raise ImportProblem('ARCHIVE_EXPANSION','Membro excede o limite de tamanho.')
                total+=size
        if total+state['expanded']>total_limit or total/max(len(data),1)>ratio:
            raise ImportProblem('ARCHIVE_EXPANSION','Pacote excede o limite de expansão.')
    try:
        if kind=='7z':
            import py7zr
            from py7zr.io import Py7zIO,WriterFactory
            buffers={};written=[0]
            class Writer(Py7zIO):
                def __init__(self):self.buffer=io.BytesIO()
                def write(self,value):
                    if self.buffer.tell()+len(value)>file_limit or written[0]+len(value)+state['expanded']>total_limit:
                        raise ImportProblem('ARCHIVE_EXPANSION','Limite excedido durante a descompressão.')
                    written[0]+=len(value);return self.buffer.write(value)
                def read(self,size=None):return self.buffer.read(-1 if size is None else size)
                def seek(self,offset,whence=0):return self.buffer.seek(offset,whence)
                def flush(self):return None
                def size(self):return self.buffer.getbuffer().nbytes
            class Factory(WriterFactory):
                def create(self,filename):
                    writer=Writer();buffers[filename]=writer;return writer
            with py7zr.SevenZipFile(io.BytesIO(data),'r',max_extract_size=total_limit-state['expanded']) as archive:
                if archive.needs_password():raise ImportProblem('ARCHIVE_ENCRYPTED','Pacotes com senha não são suportados.')
                entries=archive.list();validate([(e.filename,e.uncompressed,e.is_directory,e.is_file and not e.is_symlink) for e in entries])
                archive.extractall(factory=Factory())
                result=[]
                for entry in entries:
                    if entry.is_directory:continue
                    content=buffers[entry.filename].buffer.getvalue()
                    if len(content)!=entry.uncompressed:raise ImportProblem('ARCHIVE_INVALID','Tamanho real diverge do declarado.')
                    result.append((entry.filename,content))
                return result
        import rarfile
        # Windows 10/11 provides libarchive through tar.exe. Linux package uses bsdtar.
        if os.name=='nt' and shutil.which('tar.exe'):rarfile.BSDTAR_TOOL=shutil.which('tar.exe')
        with rarfile.RarFile(io.BytesIO(data),crc_check=True) as archive:
            if archive.needs_password():raise ImportProblem('ARCHIVE_ENCRYPTED','Pacotes com senha não são suportados.')
            entries=archive.infolist();validate([(e.filename,e.file_size,e.is_dir(),e.is_file() and not e.is_symlink()) for e in entries])
            result=[]
            for e in entries:
                if e.is_dir():continue
                with archive.open(e) as stream:content=stream.read(file_limit+1)
                if len(content)!=e.file_size or len(content)>file_limit:raise ImportProblem('ARCHIVE_EXPANSION','Tamanho real diverge do declarado ou excede o limite.')
                result.append((e.filename,content))
            return result
    except ImportProblem:raise
    except ImportError:
        raise ImportProblem('ARCHIVE_ENGINE_UNAVAILABLE','Leitor do formato ausente nesta instalação. Use ZIP ou atualize o pacote completo.') from None
    except Exception as exc:
        # No external command output or paths are exposed to API clients.
        if type(exc).__name__ in {'RarCannotExec','RarExecError'}:
            raise ImportProblem('ARCHIVE_ENGINE_UNAVAILABLE','RAR comprimido exige libarchive (bsdtar ou tar.exe do Windows). Use ZIP/7z se o leitor não estiver disponível.') from None
        if 'Password' in type(exc).__name__:
            raise ImportProblem('ARCHIVE_ENCRYPTED','Pacotes com senha não são suportados.') from None
        if 'Decompression' in type(exc).__name__:
            raise ImportProblem('ARCHIVE_EXPANSION','Descompressão interrompida por limite de segurança.') from None
        raise ImportProblem('ARCHIVE_INVALID','Pacote corrompido, multipartes ou com codec não suportado.') from None
