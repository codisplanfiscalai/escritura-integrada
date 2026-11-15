"""Host-only recovery client. Fixed operations, no shell/paths/images in RPC."""
import argparse
import json
from pathlib import Path
import re
import socket


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-directory',type=Path,required=True)
    parser.add_argument('action',choices=['status','recover-previous','reconcile-target'])
    parser.add_argument('--cutover-id')
    args=parser.parse_args()
    payload={'action':args.action}
    if args.action!='status':
        if not args.cutover_id or not re.fullmatch('[a-f0-9]{32}',args.cutover_id):parser.error('--cutover-id válido é obrigatório')
        payload.update(cutover_id=args.cutover_id,actor='host')
    path=args.project_directory.resolve(strict=True)/'.docker-updater'/'run'/'control.sock'
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(120);client.connect(str(path));client.sendall(json.dumps(payload).encode()+b'\n')
        with client.makefile('rb') as stream:raw=stream.readline(65537)
    if len(raw)>65536 or not raw.endswith(b'\n'):raise SystemExit('Resposta inválida. Confira o executor.')
    reply=json.loads(raw)
    print(json.dumps(reply['data'],ensure_ascii=False,indent=2))
    if reply['status']!=200:raise SystemExit(1)


if __name__=='__main__':main()
