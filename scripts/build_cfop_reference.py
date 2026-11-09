"""Build the bundled CONFAZ wording snapshot from the checked, extracted source.

The input is the public Anexo II text, not a list of guessed operation codes.
NF-e validation indicators are deliberately outside this source's coverage.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/referencias/cfop-confaz-20261109.txt'
TARGET = ROOT / 'app/data/cfop-confaz-20261109.json'
URL = 'https://www.confaz.fazenda.gov.br/legislacao/ajustes/sinief/cfop_cvsn_1-6.24'


def build(content):
    records, groups, current, group, annotation = [], [], None, '', ''
    for line in content.splitlines():
        line = line.strip()
        if line.startswith(('Nova redação dada ao CFOP', 'Redação anterior dada ao CFOP')):
            annotation = line
            current = None
            continue
        match = re.match(r'^([123567])\.(\d{3})\s*[-–]\s*(.+)$', line)
        if match:
            code, title = match[1] + match[2], match[3]
            current = {'code': code, 'title': title, 'note': '', 'wording_valid_from': '2024-06-01', 'wording_valid_to': '', 'legal_source': 'Ajuste SINIEF 03/24'}
            if title.isupper():
                group = code
                groups.append(current)
            else:
                current.update(direction='incoming' if code[0] in '123' else 'outgoing', group=group)
                if annotation:
                    current['legal_source'] = annotation
                    start = re.search(r'a partir de (\d{2})\.(\d{2})\.(\d{2})', annotation)
                    span = re.search(r'efeitos de (\d{2})\.(\d{2})\.(\d{2}) a (\d{2})\.(\d{2})\.(\d{2})', annotation)
                    if start: current['wording_valid_from'] = f'20{start[3]}-{start[2]}-{start[1]}'
                    if span:
                        current['wording_valid_from'] = f'20{span[3]}-{span[2]}-{span[1]}'
                        current['wording_valid_to'] = f'20{span[6]}-{span[5]}-{span[4]}'
                records.append(current)
            annotation = ''
        elif current and line and not line.startswith(('DAS ', 'ANEXO ', 'CÓDIGO FISCAL')):
            current['note'] += ('\n' if current['note'] else '') + line
    versions = {(r['code'], r['wording_valid_from']) for r in records}
    if len(versions) != len(records) or len({r['code'] for r in records}) != 619 or len(groups) != 76:
        raise ValueError('Source coverage changed; review the source and generator before replacing the snapshot.')
    return {'schema': 'escritura-cfop-reference/1', 'edition': 'confaz-anexo-II-2026-11-09',
            'source': URL, 'retrieved_on': '2026-11-09',
            'source_text_sha256': hashlib.sha256(content.encode()).hexdigest(),
            'code_count': 619, 'wording_count': len(records),
            'scope': 'Anexo II completo na página consultada, com redação-base de 01/06/2024 e alteração expressa de 7.667 em 01/02/2026. Datas são vigências da redação, não a criação original dos códigos. Não inclui indicadores de autorização DF-e do Portal NF-e, alíquotas ou enquadramento tributário.',
            'groups': groups, 'entries': records}


if __name__ == '__main__':
    TARGET.parent.mkdir(exist_ok=True)
    TARGET.write_text(json.dumps(build(SOURCE.read_text(encoding='utf-8')), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
