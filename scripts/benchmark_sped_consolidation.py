"""Reproducible synthetic-only measurement of the Gerador SPED increment.

Run preview/native separately so each process reports its own peak RSS.
This measures in-memory engines, not database/UI/export persistence throughput.
"""
import argparse
import json
import resource
import time

from app.sped_generator.consolidation import preview_nfce_groups
from app.sped_generator.native_export import consolidate_native_sped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--documents', type=int, default=90000)
    parser.add_argument('--mode', choices=('preview', 'native'), required=True)
    args = parser.parse_args()
    if args.documents < 1:
        parser.error('--documents must be positive')
    count = args.documents
    tax_id = '12345678000195'  # Synthetic fixture only, not production data.

    def rows():
        for i in range(count):
            day = f"2026-11-{min(30, i * 30 // count + 1):02d}"
            yield {'id': i + 1, 'version': 1, 'company_id': 7, 'period': '2026-11',
                   'number': str(i // 3 + 1), 'series': str(i % 3 + 1), 'key': f'{i + 1:044d}',
                   'model': '65', 'direction': 'outgoing', 'issue_date': day, 'posting_date': day,
                   'total_cents': 100, 'status': 'booked', 'source_hash': 'a' * 64,
                   'source': {'record': 'C100', 'file': 'synthetic.efd', 'line': i * 2 + 5},
                   'raw_fields': {'IND_EMIT': '0', 'COD_SIT': '00'}}

    started = time.perf_counter()
    if args.mode == 'preview':
        result = preview_nfce_groups(rows(), company_id=7, company_tax_id=tax_id, competence='2026-11')
        metrics = {'groups': result['summary']['groups'], 'total_cents': result['summary']['total_cents'],
                   'included_documents': result['summary']['included_documents']}
    else:
        lines = [f'|0000|020|0|01112026|30112026|EMPRESA FICTICIA|{tax_id}||SP|||||A|1|',
                 '|0001|0|', '|0990|3|', '|C001|0|']
        for row in rows():
            day = ''.join(reversed(row['issue_date'].split('-')))
            fields = ['1', '0', '', '65', '00', row['series'], row['number'], row['key'], day, day, '1,00']
            fields += [''] * (28 - len(fields))
            lines += ['|C100|' + '|'.join(fields) + '|',
                      '|C190|000|5102|18,00|1,00|1,00|0,18|0,00|0,00|0,00|0,00||']
        lines += ['|C990|1|']
        source = ('\r\n'.join(lines) + '\r\n').encode()
        del lines
        source_seconds = time.perf_counter() - started
        started = time.perf_counter()
        result = consolidate_native_sped(source, company_tax_id=tax_id, competence='2026-11', enabled=True)
        trace_bytes = len(json.dumps(result['trace'], ensure_ascii=False, separators=(',', ':')).encode())
        metrics = {'input_bytes': len(source), 'derived_bytes': len(result['payload']), 'trace_bytes': trace_bytes,
                   'retained_original_plus_derived_and_trace_bytes': len(source) + len(result['payload']) + trace_bytes,
                   'source_build_seconds': source_seconds, 'groups': len(result['trace']),
                   'input_c100': count, 'output_c100': sum(line.startswith(b'|C100|') for line in result['payload'].splitlines()),
                   'traced_documents': sum(len(g['members']) for g in result['trace'])}
    metrics |= {'mode': args.mode, 'documents': count, 'elapsed_seconds': time.perf_counter() - started,
                'process_peak_rss_kib_linux': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                'database_storage_changed': False,
                'scope': 'synthetic_in_memory_engine_only'}
    print(json.dumps(metrics, sort_keys=True))


if __name__ == '__main__':
    main()
