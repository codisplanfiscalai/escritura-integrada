"""Persisted CFOP response contract, independent of the browser driver."""


def checked_source_loads(imported, loaded):
    assert imported.ok, imported.text()
    assert loaded.ok, loaded.text()
    loads = loaded.json()
    assert len(loads) == 1 and loads[0]['comparison']['record_count'] == 779 and not loads[0]['parameters_active']
    assert loads[0]['id'] == imported.json()['id'], 'A consulta não retornou a carga recém-importada.'
    return loads
