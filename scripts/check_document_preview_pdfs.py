"""Optional local visual QA: pip install PyMuPDF Pillow zxing-cpp.

Run after browser_document_preview.py. Decodes symbols locally; never opens URLs.
Keeps high-resolution page PNGs for human review, including pagination.
"""
import json
from pathlib import Path
import re
import fitz
from PIL import Image
import zxingcpp

OUT=Path(__file__).resolve().parents[1]/'artifacts/document-preview'
results={}
for fixture,canvas in [('auditor_demo','DANFE-1'),('auditor_nfce','DANFC-e-2'),('auditor_cte','DACTE-99203223'),('auditor_long','DANFE-81')]:
    raw=(OUT/(fixture+'.xml')).read_bytes()
    key=re.search(br'Id="(?:NFe|CTe)([0-9]+)"',raw)[1].decode()
    qr=re.search(br'<(?:qrCode|qrCodCTe)>([^<]+)',raw)
    expected={key} if fixture!='auditor_nfce' else set()
    if qr:expected.add(qr[1].decode())
    pdf=fitz.open(OUT/(fixture+'.pdf'));codes=[]
    for index,page in enumerate(pdf):
        pix=page.get_pixmap(matrix=fitz.Matrix(4,4))
        filename=OUT/f'{fixture}-page-{index+1}.png';pix.save(filename)
        codes.extend(zxingcpp.read_barcodes(Image.open(filename)))
    pdf_values={code.text for code in codes}
    browser_codes=zxingcpp.read_barcodes(Image.open(OUT/(canvas+'-canvas.png')))
    browser_values={code.text for code in browser_codes}
    # Homologation watermark can cross the CT-e QR. Preserve the defect;
    # no deletion of watermarks or XML rewriting to make the assertion pass.
    results[fixture]={'pages':len(pdf),'expected':sorted(expected),'pdf_codes':sorted(pdf_values),
        'canvas_codes':sorted(browser_values),'pdf_match':expected<=pdf_values,'canvas_match':expected<=browser_values}
(OUT/'pdf-qa.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
print(json.dumps(results,indent=2,ensure_ascii=False))
