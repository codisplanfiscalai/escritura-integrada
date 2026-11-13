"""Deterministic errata, preservation of evidence and legal-condition coverage."""
from datetime import date
import unittest
from app.auditor_catalogs import diagnostics, load_reference
from app.auditor_catalog_corrections import corrected_reference
from app.auditor_engine.catalog import CatalogSnapshot
from app.core import DomainError


class CatalogErrataTests(unittest.TestCase):
    def test_hierarchy_headers_are_not_executable_parameters(self):
        rows=[{'ncm':'12076','ncm_level':'hierarchy','cst':'200','cclass_trib':None}]
        self.assertEqual([],diagnostics(rows,{}))
        cat=CatalogSnapshot({'entries':rows,'valid_from':'2026-01-01','valid_to':'2026-12-31'})
        self.assertEqual('NCM_NOT_PARAMETERIZED',cat.match('12076000',None,date(2026,9,1))['status'])

    def test_new_revision_preserves_original_and_customer_edits(self):
        entries,reference=load_reference()
        original=entries[636].copy()
        entries[1503]['reduction_type']='Revisão própria'
        corrected,ref=corrected_reference(entries,reference)
        self.assertEqual(original,entries[636])
        self.assertEqual('200',corrected[636]['cst'])
        self.assertEqual('Revisão própria',corrected[1503]['reduction_type'])
        self.assertEqual(2,len(ref['verified_errata']['changes']))
        self.assertNotIn('verified_errata',reference)

    def test_unknown_catalog_source_cannot_receive_bundled_errata(self):
        with self.assertRaises(DomainError):corrected_reference([],{'manifest':{'sources':[]}})

    def test_corrected_rules_need_legal_condition_review_even_if_codes_match(self):
        entries,reference=load_reference();rows,ref=corrected_reference(entries,reference)
        self.assertFalse(any(x['severity']=='error' for x in diagnostics(rows,ref)))
        cat=CatalogSnapshot({'entries':rows,'reference':ref,'valid_from':'2026-01-01','valid_to':'2026-12-31'})
        for ncm in ('03099000','15132120','34011190'):
            m=cat.match(ncm,None,date(2026,9,1))
            self.assertEqual('CONDITION_REVIEW_REQUIRED',m['status'])
            self.assertTrue(m['entry'].conditions)
