"""Contrato de verificação do Auditor em distribuições empacotadas; somente dados sintéticos."""


def xml_fixture(tax_id,year):
    return f'''<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe{'9'*44}" versao="4.00">
      <ide><mod>55</mod><serie>1</serie><nNF>SMOKE-AUDITOR</nNF><dhEmi>{year}-01-15T10:00:00-03:00</dhEmi><tpNF>1</tpNF></ide>
      <emit><CNPJ>{tax_id}</CNPJ><xNome>EMITENTE SINTETICO</xNome></emit><dest><CNPJ>88888888000191</CNPJ><xNome>DESTINATARIO SINTETICO</xNome></dest>
      <det nItem="1"><prod><cProd>TESTE</cProd><xProd>PRODUTO SINTETICO</xProd><NCM>87032100</NCM><CFOP>5102</CFOP><qCom>1</qCom><uCom>UN</uCom><vProd>100.00</vProd></prod><imposto/></det>
      <total><ICMSTot><vNF>100.00</vNF></ICMSTot></total></infNFe></NFe></nfeProc>'''


def browser_script():
    import json
    xml=json.dumps(xml_fixture('__TAX_ID__','__YEAR__'))
    return '''async () => {
        const session = await (await fetch('/api/session')).json();
        const companies = await (await fetch('/api/companies')).json();
        const cid = session.active_company_id;
        const company = companies.find(c=>c.id===cid), year=session.period.slice(0,4);
        const base=`/api/companies/${cid}/auditor`;
        const headers={'Content-Type':'application/json','X-CSRF-Token':session.csrf_token};
        const send=async(path,body)=>{const r=await fetch(base+path,{method:'POST',headers,body:JSON.stringify(body)});if(!r.ok)throw Error(`Auditor ${path}: ${r.status} ${await r.text()}`);return r.json()};
        const xml=__XML__.replace('__TAX_ID__',company.tax_id).replace('__YEAR__',year);
        const job=await send('/jobs',{name:'Smoke empacotado',mode:'standalone',start:year+'-01-01',end:year+'-12-31',idempotency_key:'auditor-packaged-smoke',files:[{filename:'smoke.xml',content_base64:btoa(xml)}]});
        let result;
        for(let n=0;n<120;n++){
            result=await (await fetch(base+'/jobs/'+job.id)).json();
            if(!['queued','running'].includes(result.status))break;
            await new Promise(resolve=>setTimeout(resolve,250));
        }
        if(result.status!=='completed'||result.result?.documents.length!==1||result.result?.totals.total_cents!==10000||result.reports?.length!==2)throw Error('Auditor empacotado falhou: '+JSON.stringify({status:result.status,error:result.error}));
        const artifacts={};
        for(const format of ['pdf','xlsx']){
            const response=await fetch(base+`/jobs/${job.id}/report?format=${format}`);
            const data=new Uint8Array(await response.arrayBuffer());
            const prefix=String.fromCharCode(...data.slice(0,4));
            if(!response.ok||data.length<1000||!(format==='pdf'?prefix==='%PDF':prefix.startsWith('PK')))throw Error('Relatório do Auditor inválido: '+format);
            artifacts[format]=data.length;
        }
        const catalog=await send('/catalogs/reference',{name:'Referência histórica - smoke',valid_from:year+'-01-01',valid_to:year+'-12-31'});
        if(catalog.entry_count!==15638||catalog.reference.cst.length!==19||catalog.reference.cclass.length!==142)throw Error('Catálogos ausentes no pacote');
        return {...artifacts,documents:1,items:result.result.documents[0].items.length,catalog_rows:catalog.entry_count};
    }'''.replace('__XML__',xml)
