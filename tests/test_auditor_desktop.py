"""Escopo de URLs do leitor nativo; execução Qt real pertence aos gates Windows/macOS."""
import unittest
from app.desktop_pdf import preview_url_allowed

class AuditorDesktopTests(unittest.TestCase):
    def test_pdf_preview_accepts_only_local_auditor_read_routes(self):
        base='http://127.0.0.1:32123'
        suffix='/api/companies/1/auditor/jobs/2/report?format=pdf&purpose=print'
        self.assertTrue(preview_url_allowed(base+suffix,base))
        self.assertTrue(preview_url_allowed(base+'/api/companies/1/auditor/jobs/2/files?file_id=3&inline=1',base))
        for url in ('https://example.invalid'+suffix,'http://127.0.0.1:32124'+suffix,base+'/api/companies',base+suffix.replace('pdf','xlsx'),base+suffix+'#external',base+suffix.replace('purpose=print','purpose=export'),'http://user@127.0.0.1:32123'+suffix):
            self.assertFalse(preview_url_allowed(url,base),url)

    def test_import_auxiliary_requires_exact_local_read_route_without_query(self):
        base='http://127.0.0.1:32123'
        suffix='/api/companies/1/imports/2/documents/0/danfe'
        self.assertTrue(preview_url_allowed(base+suffix,base))
        for url in (
            'https://example.invalid'+suffix,
            'http://127.0.0.1:32124'+suffix,
            'http://user@127.0.0.1:32123'+suffix,
            base+suffix+'?download=1', base+suffix+'?inline=',
            base+suffix+'#external', base+suffix+'/',
            base+suffix.replace('/0/', '/-1/'),
            base+suffix.replace('/danfe', '/confirm'),
            base+suffix.replace('/documents/0', '/documents/../0'),
        ):
            self.assertFalse(preview_url_allowed(url,base),url)
