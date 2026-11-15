"""Synthetic-only scale probe; not a database, UI or PVA benchmark."""
import argparse
import json
import resource
import time

from app.sped_generator.bookkeeping import generate_nfce_block_c


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--documents', type=int, default=90000)
    args = parser.parse_args()
    if args.documents < 1:
        parser.error('--documents must be positive')
    count = args.documents
    company = dict(id=7, tax_id='12345678000195', name='EMPRESA FICTICIA',
                   state='SP', ie='000000000000', ibge='3550308')
    analytics = [dict(cst_icms='000', cfop='5102', rate='18.00', operation_total='1.00',
        taxes=dict(VL_OPR='1.00', VL_BC_ICMS='1.00', VL_ICMS='0.18',
                   VL_BC_ICMS_ST='0.00', VL_ICMS_ST='0.00', VL_RED_BC='0.00', VL_IPI='0.00'))]

    def rows():
        for i in range(count):
            day = f"2026-11-{min(30, i * 30 // count + 1):02d}"
            series, number = f'{i % 3 + 1:03d}', i // 3 + 1
            first = '352611' + company['tax_id'] + '65' + series + f'{number:09d}' + '1' + f'{i + 1:08d}'
            digit = 11 - sum(int(c) * (2 + j % 8) for j, c in enumerate(reversed(first))) % 11
            key = first + str(0 if digit >= 10 else digit)
            yield dict(id=i + 1, version=1, company_id=7, period='2026-11', status='booked',
                model='65', direction='outgoing', number=str(number), series=series, key=key,
                issue_date=day, posting_date=day, total_cents=100, items=[], taxes={}, reviewed_by='fixture',
                source_hash='a' * 64, source={'record': 'C100', 'file': 'synthetic.efd'},
                raw_fields={'IND_EMIT': '0', 'COD_SIT': '00', 'IND_PGTO': '0', 'IND_FRT': '9', 'VL_MERC': '1,00'},
                analytics=analytics)

    started = time.perf_counter()
    result = generate_nfce_block_c(rows(), company=company, competence='2026-11',
                                   options=dict(profile='A', activity='1', purpose='0'))
    elapsed = time.perf_counter() - started
    print(json.dumps(dict(documents=count, elapsed_seconds=elapsed,
        c100_records=sum(line.startswith(b'|C100|') for line in result['payload'].splitlines()),
        c190_records=result['summary']['c190_records'], trace_documents=len(result['trace']),
        output_bytes=len(result['payload']), warning_groups=len(result['warnings']),
        process_peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        complete_efd=result['complete_efd'], pva_validated=False, database_storage_changed=False,
        scope='in_memory_partial_block_c_with_lazy_synthetic_fixture_generation'), sort_keys=True))


if __name__ == '__main__':
    main()
