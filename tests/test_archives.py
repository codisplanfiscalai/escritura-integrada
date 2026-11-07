"""Pacotes sintéticos: nenhuma extração em disco nem arquivo de cliente."""
import io
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import zlib
import py7zr
from app.importers import parse_file

FIXTURES=Path(__file__).parent/'fixtures'
COMPANY={'tax_id':'12345678000195'}

def seven(files,password=None):
    buffer=io.BytesIO()
    with py7zr.SevenZipFile(buffer,'w',password=password) as archive:
        for name,content in files:archive.writestr(content,name)
    return buffer.getvalue()

def rar_store(name,content):
    # Minimal RAR 3.x stored member: main, file and end headers with CRCs.
    def header(kind,flags,body):
        tail=struct.pack('<BHH',kind,flags,7+len(body))+body
        return struct.pack('<H',zlib.crc32(tail)&0xffff)+tail
    name=name.encode('ascii')
    filebody=struct.pack('<IIBIIBBHI',len(content),len(content),2,zlib.crc32(content),0,20,0x30,len(name),0x20)+name
    return b'Rar!\x1a\x07\x00'+header(0x73,0,b'\0'*6)+header(0x74,0x8000,filebody)+content+header(0x7b,0,b'')

class ArchiveTests(unittest.TestCase):
    def test_seven_and_rar_keep_fiscal_source(self):
        xml=(FIXTURES/'nfe_ficticia.xml').read_bytes()
        for name,raw in [('docs.7z',seven([('folder/nfe.xml',xml)])),('docs.rar',rar_store('nfe.xml',xml))]:
            with self.subTest(format=name):
                r=parse_file(name,raw,COMPANY);self.assertTrue(r['can_confirm'],r['issues']);self.assertEqual('100.00',r['documents'][0]['total']);self.assertIn('!/',r['documents'][0]['source']['file'])
    def test_seven_encryption_and_bounded_expansion(self):
        encrypted=seven([('x.xml',b'content')],password='synthetic')
        r=parse_file('secret.7z',encrypted,COMPANY);self.assertFalse(r['can_confirm']);self.assertIn('ARCHIVE_ENCRYPTED',{i['code'] for i in r['issues']})
        compressed=seven([('large.txt',b'0'*1_000_000)])
        r=parse_file('bomb.7z',compressed,COMPANY);self.assertFalse(r['can_confirm']);self.assertIn('ARCHIVE_EXPANSION',{i['code'] for i in r['issues']})
    def test_rar_path_traversal_and_crc(self):
        xml=(FIXTURES/'nfe_ficticia.xml').read_bytes()
        raw=rar_store('../nfe.xml',xml)
        r=parse_file('unsafe.rar',raw,COMPANY);self.assertFalse(r['can_confirm']);self.assertIn('ARCHIVE_UNSAFE_PATH',{i['code'] for i in r['issues']})
        raw=rar_store('nfe.xml',xml).replace(b'Empresa',b'EmpresX',1)
        # Alter a guaranteed byte in member data, preserving its declared CRC.
        offset=raw.index(b'<?xml');raw=raw[:offset]+b'X'+raw[offset+1:]
        r=parse_file('crc.rar',raw,COMPANY);self.assertFalse(r['can_confirm']);self.assertIn('ARCHIVE_INVALID',{i['code'] for i in r['issues']})
    def test_mixed_archive_depth_and_member_limit(self):
        nested=seven([('inner.7z',seven([('third.7z',seven([('x.xml',b'<x/>')]))]))])
        r=parse_file('nested.7z',nested,COMPANY);self.assertIn('ARCHIVE_DEPTH',{i['code'] for i in r['issues']})
        with patch('app.importers.MAX_ARCHIVE_MEMBERS',1):
            r=parse_file('members.7z',seven([('a.xml',b'<x/>'),('b.xml',b'<x/>')]),COMPANY)
            self.assertIn('ARCHIVE_MEMBERS',{i['code'] for i in r['issues']})

if __name__=='__main__':unittest.main()
