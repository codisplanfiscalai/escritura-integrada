"""Convert complete Library text extractions without inventing tax parameters."""
import argparse
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.cfop_source import build_source_bundle, load_comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-text', type=Path, required=True)
    parser.add_argument('--txt-text', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle = build_source_bundle({'pdf': args.pdf_text.read_text(encoding='utf-8'), 'txt': args.txt_text.read_text(encoding='utf-8')}, json.loads(args.metadata.read_text(encoding='utf-8')))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'cfop-carga-tabcfop-20261109.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    comparison = load_comparison(bundle, '2026-11-09')
    fields = ['code','source_description','txt_description','match','official_description','valid_from','valid_to','review_status',*next(iter(bundle['records']))['parameters_declared'].keys(),'rates_declared']
    with (args.output/'cfop-carga-conferencia.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=';');writer.writeheader()
        for row in comparison['rows']:
            writer.writerow({**{k: row[k] for k in fields if k in row}, **row['parameters_declared'], 'rates_declared': '|'.join(row['rates_declared'])})
    summary = {k: v for k, v in comparison.items() if k != 'rows'}
    (args.output/'cfop-comparacao.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__': main()
