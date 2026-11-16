"""Cadastros globais na UI real; chamado pelo smoke com instalação sintética."""
from playwright.sync_api import expect


def run(page, url, cid, nav, check, shot):
    companies = page.request.get(url + '/api/companies').json()
    other = next(c['id'] for c in companies if c['id'] != cid)

    def rows(company, kind):
        response = page.request.get(url + f'/api/companies/{company}/registrations/{kind}')
        assert response.ok, response.text()
        return response.json()

    def activate(company):
        select = page.get_by_role('combobox', name='EMPRESA ATIVA', exact=True)
        select.select_option(str(company))
        expect(select).to_be_enabled()
        expect(select).to_have_value(str(company))
        assert page.request.get(url + '/api/session').json()['active_company_id'] == company

    for label, kind, singular, tax_id in [('Terceiros', 'third-party', 'terceiro', '11144477735'),
                                           ('Contadores', 'accountant', 'contador', '52998224725')]:
        nav(label)
        expect(page.get_by_role('heading', name=label, exact=True)).to_be_visible()
        page.get_by_role('button', name='Novo ' + singular, exact=True).click()
        dialog = page.get_by_role('dialog')
        name = 'Cadastro global UI ' + singular
        dialog.get_by_label('Nome *', exact=True).fill(name)
        dialog.get_by_label('CPF *' if kind == 'accountant' else 'CPF/CNPJ', exact=True).fill(tax_id)
        if kind == 'accountant':
            dialog.get_by_label('CRC *', exact=True).fill('1SP000000')
            dialog.get_by_label('UF do CRC *', exact=True).fill('SP')
            dialog.get_by_label('Categoria profissional', exact=False).select_option('accountant')
        dialog.get_by_label('E-mail', exact=True).fill('cadastro@example.invalid')
        shot('global-' + kind + '-editor.png')
        dialog.get_by_role('button', name='Salvar cadastro', exact=True).click()
        expect(dialog).to_have_count(0)
        row = page.locator('tbody tr').filter(has_text=name)
        expect(row).to_be_visible()
        original = next(r for r in rows(cid, kind) if r['name'] == name)
        assert original['links'] == []
        activate(other)
        nav(label)
        expect(row).to_be_visible()
        assert next(r for r in rows(other, kind) if r['id'] == original['id'])['links'] == []
        row.get_by_role('button', name='Usar nesta empresa', exact=True).click()
        expect(row.get_by_role('button', name='Usar nesta empresa', exact=True)).to_have_count(0)
        used = next(r for r in rows(other, kind) if r['id'] == original['id'])
        assert [link['company_id'] for link in used['links']] == [other]
        row.get_by_role('button', name='Editar', exact=True).click()
        dialog.get_by_label('Nome *', exact=True).fill(name + ' revisado')
        dialog.get_by_role('button', name='Salvar cadastro', exact=True).click()
        expect(dialog).to_have_count(0)
        activate(cid)
        nav(label)
        expect(row).to_contain_text(name + ' revisado')
        current = next(r for r in rows(cid, kind) if r['id'] == original['id'])
        assert current['name'] == name + ' revisado' and current['links'] == used['links']
        shot('global-' + kind + '-shared.png')
        row.get_by_role('button', name='Editar', exact=True).click()
        dialog.get_by_role('button', name='Cancelar', exact=True).click()
        expect(dialog).to_have_count(0)
        row.get_by_role('button', name='Desativar', exact=True).click()
        dialog.get_by_role('button', name='Desativar', exact=True).click()
        expect(dialog).to_have_count(0)
        expect(row).to_contain_text('Inativo')
        disabled = next(r for r in rows(cid, kind) if r['id'] == original['id'])
        assert not disabled['active'] and disabled['links'] == used['links']
        check(label + ': criação/edição/cancelamento/desativação na UI, consulta sem vínculo na outra empresa e uso sem duplicar perfil')
