"""Documentos sintéticos para comparação visual e numérica; sem validade fiscal."""
from copy import deepcopy
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from lxml import etree
from io import BytesIO
from zipfile import ZipFile


def sample_archive(tax_id):
    source=(Path(__file__).parent/'fixtures/auditor_demo.xml').read_bytes()
    ns={'n':'http://www.portalfiscal.inf.br/nfe'}
    output=BytesIO()
    with ZipFile(output,'w') as archive:
        for number in range(1,9):
            root=etree.fromstring(source);inf=root.find('.//n:infNFe',ns)
            key=str(number)*44;inf.set('Id','NFe'+key)
            def put(path,value):root.find(path,ns).text=str(value)
            put('.//n:chNFe',key);put('.//n:nNF',1000+number)
            put('.//n:dhEmi',f'2026-0{(number-1)//3+1}-15T10:00:00-03:00')
            incoming=number<=4
            if incoming:
                put('.//n:emit/n:CNPJ','88888888000199')
                node=root.find('.//n:dest/n:CPF',ns);node.tag='{'+ns['n']+'}CNPJ';node.text=tax_id
                put('.//n:emit/n:xNome','FORNECEDOR SINTÉTICO '+str(number))
                put('.//n:dest/n:xNome','EMPRESA AUDITADA SINTÉTICA')
            else:put('.//n:emit/n:CNPJ',tax_id);put('.//n:dest/n:xNome','CLIENTE SINTÉTICO '+str(number))
            template=inf.find('n:det',ns);inf.remove(template)
            total=Decimal(0);base_total=Decimal(0)
            for item in range(1,4):
                det=deepcopy(template);det.set('nItem',str(item))
                def itemput(path,value):det.find(path,ns).text=str(value)
                value=Decimal(100+number*10+item)
                itemput('.//n:vProd',value);itemput('.//n:vUnCom',value);itemput('.//n:vUnTrib',value)
                itemput('.//n:cProd',f'PROD-{item:03}');itemput('.//n:xProd',f'PRODUTO SINTÉTICO {item} PARA COMPARAÇÃO')
                itemput('.//n:cEAN',f'78900000000{item:02}');itemput('.//n:cEANTrib',f'78900000000{item:02}')
                itemput('.//n:infAdProd','Lote sintético. Sem validade fiscal.')
                base=value-Decimal('36.50');base_total+=base
                itemput('.//n:gIBSCBS/n:vBC',base)
                ibs=(base*Decimal('.001')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                cbs=(base*Decimal('.009')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                itemput('.//n:vIBSUF',ibs);itemput('.//n:vIBS',ibs);itemput('.//n:vCBS',cbs)
                inf.insert(list(inf).index(inf.find('n:total',ns)),det);total+=value
            for tag,value in [('vNF',total),('vProd',total),('vPIS','19.50'),('vCOFINS','90.00')]:put('.//n:ICMSTot/n:'+tag,value)
            put('.//n:vBCIBSCBS',base_total)
            archive.writestr(f'documento-{number}.xml',etree.tostring(root,encoding='utf-8',xml_declaration=True))
    return output.getvalue()
