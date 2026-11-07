"""Ações reais de arquivo no WebEngine empacotado, sem acessar dados do usuário."""
import json


def cases(cid, year):
    prefix=f'/api/companies/{cid}/business-reports/'
    params=f'?start={year}-01-01&end={year}-12-31'
    return [
        {'name':'download direto legado', 'kind':'legacy', 'url':prefix+'fiscal-documents'+params+'&format=csv'},
        {'name':'exportação fiscal PDF', 'kind':'download', 'url':prefix+'fiscal-documents'+params+'&format=pdf'},
        {'name':'exportação contábil Excel', 'kind':'download', 'url':prefix+'diary'+params+'&format=xlsx'},
        {'name':'cancelamento financeiro', 'kind':'cancel', 'url':prefix+'financial'+params+'&format=csv'},
        {'name':'prévia fiscal', 'kind':'preview', 'url':prefix+'fiscal-documents'+params+'&format=pdf&purpose=print'},
        {'name':'prévia contábil', 'kind':'preview', 'url':prefix+'diary'+params+'&format=pdf&purpose=print'},
        {'name':'prévia financeira', 'kind':'preview', 'url':prefix+'financial'+params+'&format=pdf&purpose=print'},
    ]


def click_script(case):
    url=json.dumps(case['url'])
    if case['kind']=='legacy':return f'window.location.href={url}'
    target="a.target='_blank';a.rel='noopener';" if case['kind']=='preview' else "a.download='';"
    return "(() => {const a=document.createElement('a');a.href="+url+";"+target+"document.body.append(a);a.click();a.remove();})()"
