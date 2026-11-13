"""Synthetic purchase context, configurable defaults and immutable XML provenance."""
import unittest
import test_fiscal_import as base


class PurchaseReclassificationTests(unittest.TestCase):
    setUp = base.FiscalImportTests.setUp
    tearDown = base.FiscalImportTests.tearDown
    create_company = base.FiscalImportTests.create_company
    activate = base.FiscalImportTests.activate
    scope = base.FiscalImportTests.scope
    post = base.FiscalImportTests.post
    xml = base.FiscalImportTests.xml
    preview = base.FiscalImportTests.preview
    mapping = base.FiscalImportTests.mapping
    def prepared(self, batch, **extra):
        return self.post(f"/imports/{batch['id']}/posting-preview", extra)

    def raw(self, source='5101', state='SP'):
        return self.xml().replace(b'<CFOP>5102</CFOP>', f'<CFOP>{source}</CFOP>'.encode()).replace(b'</emit>', f'<enderEmit><UF>{state}</UF></enderEmit></emit>'.encode())

    def config(self, source='5101', target='1102', destination='resale', **extra):
        data = {'version': 0, 'purchase_destination': destination, 'fallback_mappings': [{'source_cfop': source, 'target_cfop': target, 'purchase_destination': destination}], 'reason': 'Caso sintético explícito', 'responsible': 'Teste', **extra}
        result = self.client.put(self.scope('/fiscal-import-settings'), json=data)
        self.assertEqual(200, result.status_code, result.text)
        return result.json()

    def prepare(self, batch, **extra):
        return self.prepared(batch, document_overrides={'documents:0': {'posting_date_confirmed': True}}, **extra)['documents'][0]

    def test_catalog_is_verified_configurable_not_activated(self):
        result = self.client.get(self.scope('/fiscal-import-settings/catalog'))
        self.assertEqual(200, result.status_code, result.text)
        data = result.json()
        self.assertGreaterEqual(len(data['rows']), 40)
        self.assertTrue(data['activation_required'])
        self.assertTrue(all(r['source'] and r['source_title'] and r['target_title'] for r in data['rows']))
        settings = self.client.get(self.scope('/fiscal-import-settings')).json()
        self.assertEqual([], settings['fallback_mappings'])

    def test_fallback_requires_destination_and_preserves_source(self):
        self.config(); batch = self.preview(self.raw()); doc = self.prepare(batch)
        self.assertTrue(doc['import_posting']['eligible'], doc['import_posting'])
        self.assertEqual('5101', doc['items'][0]['source_cfop'])
        self.assertEqual('1102', doc['items'][0]['cfop'])
        self.assertEqual('fallback', doc['import_posting']['mappings'][0]['origin'])
        self.assertTrue(doc['import_posting']['review_pending'])
        other = self.prepare(batch, purchase_destination='consumption')
        self.assertFalse(other['import_posting']['eligible'])

    def test_interstate_and_unknown_geography_are_guarded(self):
        self.config(source='6101', target='2102')
        correct = self.prepare(self.preview(self.raw('6101', 'RJ')))
        self.assertTrue(correct['import_posting']['eligible'], correct['import_posting'])
        wrong = self.prepare(self.preview(self.raw('6101', 'SP')))
        self.assertFalse(wrong['import_posting']['eligible'])
        unknown = self.prepare(self.preview(self.raw('6101', '')))
        self.assertFalse(unknown['import_posting']['eligible'])

    def test_specific_mapping_overrides_fallback_and_conflicts_block(self):
        self.config(); self.mapping(source_cfop='5101', target_cfop='1101', purchase_destination='industrialization')
        batch = self.preview(self.raw()); doc = self.prepare(batch, purchase_destination='industrialization')
        self.assertEqual('1101', doc['items'][0]['cfop'])
        self.assertEqual('company', doc['import_posting']['mappings'][0]['origin'])
        self.mapping(source_cfop='5101', target_cfop='1102', ncm=doc['items'][0]['ncm'])
        conflict = self.prepare(batch, purchase_destination='industrialization')
        self.assertFalse(conflict['import_posting']['eligible'])
        self.assertIn('ambiguidade', conflict['import_posting']['reason'])

    def test_proposed_receipt_date_requires_explicit_confirmation(self):
        self.config(); batch = self.preview(self.raw())
        doc = self.prepared(batch)['documents'][0]
        self.assertFalse(doc['import_posting']['eligible'])
        self.assertIn('recebimento', doc['import_posting']['reason'])
        self.assertTrue(self.prepare(batch)['import_posting']['eligible'])

    def test_company_scoping_and_stale_configuration(self):
        first = self.config()
        self.assertEqual([], self.core.fiscal_import_settings(self.b['id'])['fallback_mappings'])
        self.client.put(self.scope('/fiscal-import-settings'), json=first)
        response = self.client.put(self.scope('/fiscal-import-settings'), json=first)
        self.assertEqual(409, response.status_code)

    def test_unrelated_return_not_silently_mapped(self):
        self.config(); doc = self.prepare(self.preview(self.raw('5202')))
        self.assertFalse(doc['import_posting']['eligible'])
        self.assertEqual('5202', doc['items'][0]['source_cfop'])

    def test_catalog_copy_tracks_actor_and_preserves_lineage_when_customized(self):
        catalog = self.client.get(self.scope('/fiscal-import-settings/catalog')).json()
        settings = self.config(source_catalog_version=catalog['version'], fallback_mappings=catalog['rows'])
        self.assertEqual(catalog['version'], settings['source_catalog_version'])
        self.assertTrue(settings['catalog_imported_by'])
        imported_at = settings['catalog_imported_at']
        settings.pop('source_catalog_version')
        settings['fallback_mappings'] = settings['fallback_mappings'][:1]
        result = self.client.put(self.scope('/fiscal-import-settings'), json=settings)
        self.assertEqual(200, result.status_code, result.text)
        self.assertEqual(imported_at, result.json()['catalog_imported_at'])
        self.assertEqual(40, len(self.client.get(self.scope('/fiscal-import-settings/catalog')).json()['rows']))

    def test_return_pattern_is_saved_with_warning_but_never_applied(self):
        settings = self.config(source='5202')
        self.assertTrue(settings['warnings'])
        doc = self.prepare(self.preview(self.raw('5202')))
        self.assertFalse(doc['import_posting']['eligible'])
        self.assertIn('Natureza', doc['import_posting']['reason'])

    def test_document_and_item_context_override_batch_and_company(self):
        self.config()
        batch = self.preview(self.raw())
        payload = {'purchase_destination': 'consumption', 'document_overrides': {'documents:0': {'posting_date_confirmed': True, 'purchase_destination': 'fixed_asset', 'item_destinations': {'1': 'resale'}}}}
        doc = self.prepared(batch, **payload)['documents'][0]
        self.assertTrue(doc['import_posting']['eligible'], doc['import_posting'])
        self.assertEqual('item', doc['import_posting']['mappings'][0]['destination_origin'])
        self.assertEqual('resale', doc['items'][0]['purchase_destination'])
        self.assertTrue(doc['posting_lines'])

    def test_date_confirmation_rejects_truthy_strings(self):
        batch = self.preview(self.raw())
        result = self.client.post(self.scope(f"/imports/{batch['id']}/posting-preview"), json={'document_overrides': {'documents:0': {'posting_date_confirmed': 'true'}}})
        self.assertEqual(400, result.status_code)

    def test_specific_mapping_geography_blocks_contradiction_but_manual_override_is_explicit(self):
        self.mapping(source_cfop='6101', target_cfop='1102')
        batch = self.preview(self.raw('6101', 'RJ'))
        doc = self.prepare(batch)
        self.assertFalse(doc['import_posting']['eligible'])
        self.assertIn('UF', doc['import_posting']['reason'])
        explicit = self.prepared(batch, document_overrides={'documents:0': {'posting_date_confirmed': True, 'cfop': '2102'}})['documents'][0]
        self.assertTrue(explicit['import_posting']['eligible'], explicit['import_posting'])
        self.assertEqual('document', explicit['import_posting']['mappings'][0]['origin'])

    def test_return_specific_mapping_has_visible_context_warning(self):
        mapping = self.mapping(source_cfop='5202', target_cfop='1102')
        self.assertEqual('OPERATION_CONTEXT_REVIEW', mapping['warnings'][0]['code'])
        listed = self.client.get(self.scope('/fiscal-import-mappings')).json()
        self.assertEqual(mapping['warnings'], listed[0]['warnings'])

    def rtc(self, protocol=True):
        raw = self.raw().replace(b'</total>', b'<vNFTot>110.00</vNFTot></total>')
        if not protocol:
            import re
            raw = re.sub(rb'<protNFe.*?</protNFe>', b'', raw, flags=re.S)
        return raw

    def review(self):
        return {'basis': 'vNF', 'source': 'Política de conferência sintética', 'responsible': 'Teste', 'reason': 'Reconciliado para escrituração; sem certificação RTC'}

    def test_rtc_requires_explicit_decision_and_preserves_declared_totals(self):
        self.config(); batch = self.preview(self.rtc())
        blocked = self.prepare(batch)
        self.assertFalse(blocked['import_posting']['eligible'])
        self.assertIn('vNFTot', blocked['import_posting']['reason'])
        allowed = self.prepare(batch, total_review=self.review())
        self.assertTrue(allowed['import_posting']['eligible'], allowed['import_posting'])
        self.assertEqual(blocked['total'], allowed['total'])
        self.assertEqual('110.00', allowed['declared_new_total'])
        self.assertEqual(allowed['total_comparison'], allowed['import_posting']['total_comparison'])
        self.assertEqual('batch', allowed['import_posting']['total_review_origin'])
        self.assertEqual('vNF', allowed['total_review']['basis'])

    def test_rtc_review_does_not_release_missing_protocol_and_rejects_bad_fields(self):
        self.config(); batch = self.preview(self.rtc(False))
        self.assertFalse(self.prepare(batch, total_review=self.review())['import_posting']['eligible'])
        for review in [self.review() | {'basis': 'vNFTot'}, self.review() | {'untrusted': True}, self.review() | {'reason': ''}]:
            response = self.client.post(self.scope(f"/imports/{batch['id']}/posting-preview"), json={'total_review': review})
            self.assertEqual(400, response.status_code, response.text)

    def test_rtc_document_decision_wins_and_hash_covers_batch_decision(self):
        self.config(); batch = self.preview(self.rtc())
        overrides = {'documents:0': {'posting_date_confirmed': True, 'total_review': self.review() | {'reason': 'Decisão individual'}}}
        one = self.prepared(batch, total_review=self.review(), document_overrides=overrides)
        doc = one['documents'][0]
        self.assertEqual('Decisão individual', doc['total_review']['reason'])
        self.assertEqual('document', doc['import_posting']['total_review_origin'])
        two = self.prepared(batch, total_review=self.review() | {'reason': 'Decisão lote alterada'}, document_overrides=overrides)
        self.assertNotEqual(one['posting_hash'], two['posting_hash'])
