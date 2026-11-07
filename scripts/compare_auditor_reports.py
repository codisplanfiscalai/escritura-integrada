"""Compara modelos do ZIP 1.2.2 com relatórios nativos usando a MESMA amostra.
Uso: python -m scripts.compare_auditor_reports --original /caminho/auditorfiscal-1.2.2
A origem é só referência de validação; não é dependência da aplicação.
"""
import argparse,base64,importlib,json,sys,types
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from openpyxl import load_workbook
from pypdf import PdfReader


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--original',type=Path,required=True);parser.add_argument('--output',type=Path,default=Path('artifacts/auditor-comparison'));args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'tests'))
    from test_auditor_integration import AuditorIntegrationTests
    from auditor_samples import sample_archive
    from app.auditor_reports import export_audit
    package=types.ModuleType('original_auditor');package.__path__=[str(args.original/'services/fiscal-engine/app')];sys.modules['original_auditor']=package
    pdf=importlib.import_module('original_auditor.reports.pdf_report')
    excel=importlib.import_module('original_auditor.reports.excel_report')
    test=AuditorIntegrationTests();test.setUp();args.output.mkdir(parents=True,exist_ok=True)
    try:
        archive=sample_archive(test.a['tax_id']);(args.output/'amostra-sintetica.zip').write_bytes(archive)
        job=test.submit(files=[{'filename':'amostra.zip','content_base64':base64.b64encode(archive).decode()}])
        assert job['status']=='completed',job['error']
        (args.output/'resultado.json').write_text(json.dumps(job,ensure_ascii=False,indent=2))
        docs=job['result']['documents'];findings=job['findings'];stats=job['analytics'];summary=stats['overview']|{'classification_ok':stats['classification_ok']}
        company={'legal_name':job['snapshot']['company']['name']};period={'start':job['start'],'end':job['end']};catalog={'version':'Sem catálogo publicado','sha256':'Não informado'}
        pdf.build_pdf(args.output/'original-1.2.2.pdf',company,period,summary,docs,findings,catalog,'1.2.2')
        excel.build_excel(args.output/'original-1.2.2.xlsx',company,period,summary,docs,findings,catalog,[])
        for fmt in ('pdf','xlsx'):(args.output/f'escritura-corrigido.{fmt}').write_bytes(export_audit(job,fmt)[0])
        original=load_workbook(args.output/'original-1.2.2.xlsx',data_only=True);native=load_workbook(args.output/'escritura-corrigido.xlsx',data_only=True)
        comparisons={}
        def rows(wb,name):
            data=list(wb[name].values);return [dict(zip(data[0],r)) for r in data[1:]]
        from app.auditor_presentation import COMPONENTS
        specifications={
            'Notas - Sintético':['NF','Chave','Valor NF','Base IBS/CBS','IBS','CBS'],
            'Itens - Analítico':['NF','Item','NCM','vProd','vPIS','vCOFINS','Base XML','Base recalculada'],
            'Tributos':['NF','Item','NCM','ICMS','CST PIS','PIS','CST COFINS','COFINS'],
            'Auditoria NCM-ClassTrib':['NF','Item','Produto','NCM','EX','CST encontrada','cClass encontrada','CST esperada','cClass esperada','Situação'],
            'IBS e CBS':['NF','Item','NCM','CST','cClassTrib','Base XML',('Base recalculada','Base assistida'),'Diferença base','IBS XML',('IBS recalc.','IBS recálculo'),'CBS XML',('CBS recalc.','CBS recálculo'),'Situação'],
            'Memória de Cálculo':['NF','Item',*COMPONENTS,'Base XML',('Base UB16-10','Base assistida UB16-10'),('Diferença','Diferença base')],
            'Entradas x Saídas':['Produto / identificador','NCM','Unidade','Qtd. entrada','Qtd. saída',('Valor de entrada','Valor entrada'),('Valor de saída','Valor saída'),'Custo estimado','Margem estimada'],
            'Inconsistências':['Severidade','NF','Item','Categoria','Regra','Título',('Evidência','Descrição'),'Impacto','Ação recomendada',('Status','Situação')],
            'Parametrização Utilizada':['NCM','EX','CST esperada','cClass esperada',('Linha origem','Linha')],
        }
        for sheet,fields in specifications.items():
            old,new=rows(original,sheet),rows(native,sheet);assert len(old)==len(new),(sheet,len(old),len(new))
            count=0
            for a,b in zip(old,new):
                for field in fields:
                    origin,target=field if isinstance(field,tuple) else (field,field)
                    left,right=a[origin],b[target]
                    if origin in {'NF','NCM','CST PIS','CST COFINS'}:left,right=str(left),str(right)
                    assert left==right,(sheet,origin,target,left,right)
                    count+=1
            comparisons[sheet]={'rows':len(old),'equal_cells':count,'fields':fields}
        result={'source':'auditorfiscal-1.2.2(1).zip','source_sha256':'f738450837965543a190ac5304362abe868aee5dc9f35d19b8725a7dd6dbe2fb','sample':'8 documentos sintéticos / 24 itens / 4 entradas / 4 saídas','total':'3528.00','comparisons':comparisons,'original_pdf_pages':len(PdfReader(args.output/'original-1.2.2.pdf').pages),'native_pdf_pages':len(PdfReader(args.output/'escritura-corrigido.pdf').pages),'limits':['Comparação visual exige inspeção dos PDFs renderizados.','Amostra sintética regular; não certifica cenários tributários especiais.','Tratamentos, memória detalhada e diagnósticos são acréscimos nativos.']}
        (args.output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:test.tearDown()

if __name__=='__main__':main()
