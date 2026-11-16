"""Optional local visual QA: pip install PyMuPDF Pillow zxing-cpp.

Run after browser_document_preview.py. Decodes symbols locally; never opens URLs.
Keeps high-resolution page PNGs for human review, including pagination.
"""
import json
from lxml import etree
from pathlib import Path
import re
import fitz
from PIL import Image
import zxingcpp

OUT=Path(__file__).resolve().parents[1]/'artifacts/document-preview'
results={}
for fixture,canvas in [('auditor_demo','DANFE-1'),('auditor_nfce','DANFC-e-2'),('auditor_cte','DACTE-99203223'),('auditor_cte_long','DACTE-99203224'),('auditor_cte_stress','DACTE-99203225'),('auditor_long','DANFE-81')]:
    raw=(OUT/(fixture+'.xml')).read_bytes()
    key=re.search(br'Id="(?:NFe|CTe)([0-9]+)"',raw)[1].decode()
    qr=etree.fromstring(raw).xpath('string(.//*[local-name()="qrCode" or local-name()="qrCodCTe"])')
    expected={key} if fixture!='auditor_nfce' else set()
    if qr:expected.add(qr)
    pdf=fitz.open(OUT/(fixture+'.pdf'));codes=[]
    for index,page in enumerate(pdf):
        pix=page.get_pixmap(matrix=fitz.Matrix(4,4))
        filename=OUT/f'{fixture}-page-{index+1}.png';pix.save(filename)
        codes.extend(zxingcpp.read_barcodes(Image.open(filename)))
    pdf_values={code.text for code in codes}
    browser_codes=zxingcpp.read_barcodes(Image.open(OUT/(canvas+'-canvas.png')))
    browser_values={code.text for code in browser_codes}
    results[fixture]={'pages':len(pdf),'expected':sorted(expected),'pdf_codes':sorted(pdf_values),
        'canvas_codes':sorted(browser_values),'pdf_match':expected<=pdf_values,'canvas_match':expected<=browser_values}
    if fixture.startswith('auditor_cte'):
        variants = {}
        for index,sheet in enumerate(pdf):
            for scale in (1.25, 2, 4):
                pix = sheet.get_pixmap(matrix=fitz.Matrix(scale, scale))
                values = {c.text for c in zxingcpp.read_barcodes(Image.frombytes('RGB', (pix.width, pix.height), pix.samples))}
                name = 'pdf_scale_'+str(scale) if index==0 else f'pdf_page_{index+1}_scale_{scale}'
                variants[name] = {'match': expected <= values, 'codes': sorted(values)}
        for index in range(len(pdf)):
            for zoom in ('0.75', '1', '1.25', '1.5'):
                suffix='' if index==0 else f'-page-{index+1}'
                values = {c.text for c in zxingcpp.read_barcodes(Image.open(OUT/(canvas+suffix+'-zoom-'+zoom+'.png')))}
                variants['canvas'+suffix+'_zoom_'+zoom] = {'match': expected <= values, 'codes': sorted(values)}
        results[fixture]['decoding_variants'] = variants
        text = re.sub(r'\s+','', ''.join(p.get_text() for p in pdf))
        source = etree.fromstring(raw)
        missing = [node.text for node in source.xpath('.//*[local-name()="xNome" or local-name()="xLgr" or local-name()="xCpl" or local-name()="xMun" or local-name()="xTexto" or local-name()="chave"]') if re.sub(r'\s+','',node.text or '') not in text]
        collisions = []
        outside = []
        for number,sheet in enumerate(pdf,1):
            spans = [s for b in sheet.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans'] if s['text'].strip()]
            rectangles = [fitz.Rect(item[1]) for path in sheet.get_drawings() for item in path['items'] if item[0]=='re' and item[1].width>14 and item[1].height>10]
            for i,span in enumerate(spans):
                bounds = fitz.Rect(span['bbox'])
                # Receipt and footer are fixed blocks; body spans must be contained
                # in a drawn cell, allowing font bounding-box descent by 1mm.
                if bounds.y0 > 76 and bounds.y1 < sheet.rect.height-79:
                    if not any((r+(-2.84,-2.84,2.84,2.84)).contains(bounds) for r in rectangles):
                        outside.append({'page':number,'text':span['text']})
                for other in spans[i+1:]:
                    overlap = bounds & fitz.Rect(other['bbox'])
                    if abs(span['origin'][1]-other['origin'][1])<1 and overlap.width>1 and overlap.height>1:
                        collisions.append({'page':number,'left':span['text'],'right':other['text']})
        results[fixture]['layout'] = {'missing_fields':missing,'same_line_collisions':collisions,'outside_cells':outside}
        results[fixture]['layout_status'] = 'PASS' if not (missing or collisions or outside) else 'FAIL'
(OUT/'pdf-qa.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
print(json.dumps(results,indent=2,ensure_ascii=False))

assert all(r['pdf_match'] and r['canvas_match'] and all(v['match'] for v in r.get('decoding_variants',{}).values()) for r in results.values()), 'Symbol decoding regression; see pdf-qa.json (layout status reported separately)'

assert all(r.get('layout_status','PASS') == 'PASS' for r in results.values()), 'Layout regression; see pdf-qa.json'
