"""Build/sign the read-only Apple helper natively. No third-party crypto SDK."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def manifest(binary, destination=None):
    value={'protocol':1,'build':'production','architecture':platform.machine(),
           'sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
    destination=Path(destination) if destination is not None else binary.with_name('manifest.json')
    destination.write_text(json.dumps(value,sort_keys=True)+'\n')
    destination.chmod(0o644)
    return value


def build():
    if sys.platform!='darwin' or platform.machine() not in {'x86_64','arm64'}:
        raise RuntimeError('Build A1 exige macOS Intel/ARM nativo.')
    directory=ROOT/'build/native-a1';directory.mkdir(parents=True,exist_ok=True)
    binary=directory/'EscrituraA1'
    subprocess.run(['xcrun','swiftc','-O','-swift-version','5','-target',platform.machine()+'-apple-macosx15.0',
                    str(ROOT/'native/EscrituraA1.swift'),'-framework','Security','-framework','CFNetwork','-o',str(binary)],check=True,timeout=120)
    binary.chmod(0o755)
    architectures=subprocess.check_output(['lipo','-archs',str(binary)],text=True).split()
    if architectures!=[platform.machine()]:raise RuntimeError('Arquitetura A1 divergente.')
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(binary)],check=True,timeout=30)
    subprocess.run(['/usr/bin/codesign','--verify','--strict',str(binary)],check=True,timeout=30)
    info=manifest(binary)
    result=subprocess.run([str(binary)],input=b'{"protocol":1,"action":"version"}',capture_output=True,check=True,timeout=10)
    if json.loads(result.stdout)!={'protocol':1,'build':'production','ok':True}:raise RuntimeError('Protocolo/build A1 inválido.')
    return binary,info


if __name__=='__main__':
    binary,info=build();print(json.dumps(info,sort_keys=True))
