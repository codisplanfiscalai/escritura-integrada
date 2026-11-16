"""Small platform boundary: private directories and per-user Windows DPAPI.

Native Windows calls need Windows acceptance testing; Linux tests use injected boundaries.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import stat
import uuid

WINDOWS = os.name == 'nt'
KEY_MAGIC = b'EI-DPAPI-1\0'
PRIVATE_SDDL = 'D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)'


def reparse(path):
    info = Path(path).lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _windows_directory(path, create):
    import ctypes as c
    from ctypes import wintypes as w
    advapi = c.WinDLL('advapi32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    volume = c.create_unicode_buffer(32768)
    locate = kernel.GetVolumePathNameW
    locate.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]; locate.restype = w.BOOL
    flags = w.DWORD()
    info = kernel.GetVolumeInformationW
    info.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD, c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.POINTER(w.DWORD), w.LPWSTR, w.DWORD]
    info.restype = w.BOOL
    if (not locate(str(Path(path).parent), volume, len(volume)) or
            not info(volume.value, None, 0, None, None, c.byref(flags), None, 0) or not flags.value & 8):
        raise OSError('O volume precisa preservar e aplicar ACLs; FAT/exFAT não são aceitos.')
    class Attributes(c.Structure):
        _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]
    sd = c.c_void_p()
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.POINTER(w.DWORD)]
    convert.restype = w.BOOL
    kernel.LocalFree.argtypes = [c.c_void_p]; kernel.LocalFree.restype = c.c_void_p
    if not convert(PRIVATE_SDDL, 1, c.byref(sd), None):
        raise OSError('Não foi possível construir a ACL privada.')
    try:
        if create:
            call = kernel.CreateDirectoryW
            call.argtypes = [w.LPCWSTR, c.POINTER(Attributes)]; call.restype = w.BOOL
            attributes = Attributes(c.sizeof(Attributes), sd, False)
            if not call(str(path), c.byref(attributes)):
                if c.get_last_error() == 183: raise FileExistsError('Diretório já existe.')
                raise OSError('Criação de diretório privado recusada.')
        else:
            call = advapi.SetFileSecurityW
            call.argtypes = [w.LPCWSTR, w.DWORD, c.c_void_p]; call.restype = w.BOOL
            if not call(str(path), 4 | 0x80000000, sd):
                raise OSError('Não foi possível restringir a ACL do diretório de backup.')
    finally:
        kernel.LocalFree(sd)


def private_directory(path, exist_ok=False):
    path = Path(path)
    if path.exists() or path.is_symlink():
        if not exist_ok: raise FileExistsError('Diretório já existe.')
        if reparse(path) or not path.is_dir(): raise ValueError('Diretório indireto recusado.')
        if WINDOWS: _windows_directory(path, False)
        else: path.chmod(0o700)
    elif WINDOWS:
        _windows_directory(path, True)
    else:
        path.mkdir(mode=0o700)
    return path


def safe_remove(path):
    """Logical removal only; refuse reparse points, symlinks and special files."""
    path = Path(path)
    def inspect(node):
        if reparse(node): raise ValueError('Resíduo com link ou reparse point; revisão manual necessária.')
        info = node.lstat()
        if stat.S_ISDIR(info.st_mode):
            for child in node.iterdir(): inspect(child)
        elif not stat.S_ISREG(info.st_mode):
            raise ValueError('Resíduo não regular; revisão manual necessária.')
    inspect(path)
    shutil.rmtree(path)


@contextmanager
def temporary_directory(parent, prefix):
    # The Windows DACL is set atomically at directory creation, before plaintext exists.
    path = private_directory(Path(parent) / (prefix + uuid.uuid4().hex))
    try: yield path
    finally: safe_remove(path)


def dpapi(value, protect):
    import ctypes as c
    from ctypes import wintypes as w
    class Blob(c.Structure):
        _fields_ = [('size', w.DWORD), ('data', c.POINTER(c.c_ubyte))]
    raw = (c.c_ubyte * len(value)).from_buffer_copy(value)
    incoming, outgoing = Blob(len(value), raw), Blob()
    crypt = c.WinDLL('crypt32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [c.c_void_p]; kernel.LocalFree.restype = c.c_void_p
    if protect:
        call = crypt.CryptProtectData
        call.argtypes = [c.POINTER(Blob), w.LPCWSTR, c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
    else:
        call = crypt.CryptUnprotectData
        call.argtypes = [c.POINTER(Blob), c.POINTER(w.LPWSTR), c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
    call.restype = w.BOOL
    # UI_FORBIDDEN, current-user scope; never CRYPTPROTECT_LOCAL_MACHINE.
    if not call(c.byref(incoming), None, None, None, None, 1, c.byref(outgoing)):
        raise ValueError('DPAPI recusou a operação para este usuário/ambiente.')
    try: return c.string_at(outgoing.data, outgoing.size)
    finally: kernel.LocalFree(outgoing.data)


def encode_key(payload):
    return KEY_MAGIC + dpapi(payload, True) if WINDOWS else payload


def decode_key(payload):
    if WINDOWS:
        if not payload.startswith(KEY_MAGIC): raise ValueError('Windows exige chave local protegida por DPAPI.')
        return dpapi(payload[len(KEY_MAGIC):], False)
    if payload.startswith(KEY_MAGIC): raise ValueError('Chave DPAPI requer o usuário Windows original; recupere usando a frase secreta.')
    return payload
