"""Arithmetic diagnostics only; never change or certify the fiscal treatment."""
from .core import DomainError, money, decimal_text


def document_total_issue(document):
    """Reconcile NF-e product totals with declared adjustments, not gross items with vNF."""
    items = document.get('items') or []
    try:
        products = 0
        for item in items:
            indicator = str(item.get('declared_product_fields', {}).get('indTot', '1'))
            if indicator not in {'0', '1'}:
                return 'ITEM_VALUE', 'Indicador indTot inválido; confira os itens antes de conciliar o total.'
            if indicator == '1': products += money(item.get('total'), 'Total do item')
        taxes = {key.replace('/', '.'): value for key, value in (document.get('taxes') or {}).items()}
        if not any(key.startswith('ICMSTot.') for key in taxes):
            if products != document['total_cents']:
                return 'ITEM_HEADER_DIFFERENCE', 'Itens e total documental diferem; os componentes de frete, desconto e acréscimos não estão disponíveis para conciliação.'
            return None
        def component(name):
            return money(taxes.get('ICMSTot.' + name, '0.00'), name)
        if 'ICMSTot.vProd' not in taxes or 'ICMSTot.vNF' not in taxes:
            return 'TOTAL_COMPONENTS_REVIEW', 'Totalizadores XML incompletos: confira vProd e vNF antes de conciliar o documento.'
        if money(taxes.get('ISSQNtot.vServ', '0.00'), 'Serviços'):
            return 'TOTAL_COMPONENTS_REVIEW', 'Nota conjugada com serviços: confira a composição específica de produtos, serviços e total documental.'
        declared_products = component('vProd')
        if products != declared_products:
            return 'ITEM_HEADER_DIFFERENCE', f'Itens que compõem o total somam R$ {decimal_text(products)}, diferente do vProd declarado de R$ {decimal_text(declared_products)}.'
        deduction = 0
        if component('vICMSDeson'):
            amounts = 0
            for item in items:
                item_tax = {k.replace('/', '.'): v for k,v in item.get('taxes', {}).items()}
                deson = [v for k,v in item_tax.items() if k.endswith('.vICMSDeson')]
                if not deson: continue
                flags = [str(v) for k,v in item_tax.items() if k.endswith('.indDeduzDeson')]
                if len(deson) != 1 or len(flags) != 1 or flags[0] not in {'0', '1'}:
                    return 'TOTAL_COMPONENTS_REVIEW', 'Há ICMS desonerado sem indicação inequívoca de dedução. Confira os componentes, sem presumir abatimento.'
                amount = money(deson[0], 'ICMS desonerado');amounts += amount
                if flags[0] == '1': deduction += amount
            if amounts != component('vICMSDeson'):
                return 'TOTAL_COMPONENTS_REVIEW', 'ICMS desonerado dos itens diverge do total declarado; confira a dedução.'
        additions = sum(component(name) for name in ('vST', 'vFCPST', 'vFrete', 'vSeg', 'vOutro', 'vII', 'vIPI', 'vIPIDevol'))
        expected = products - component('vDesc') - deduction + additions
        if expected != component('vNF') or component('vNF') != document['total_cents']:
            return 'ITEM_HEADER_DIFFERENCE', f'Composição declarada: produtos − descontos − desoneração dedutível + acréscimos = R$ {decimal_text(expected)}; vNF da origem R$ {decimal_text(component("vNF"))}; total escriturado R$ {decimal_text(document["total_cents"])}. Confira a diferença; nenhum valor foi alterado.'
        return None
    except (DomainError, TypeError, AttributeError):
        return 'ITEM_VALUE', 'Há item ou componente do total sem valor numérico válido.'
