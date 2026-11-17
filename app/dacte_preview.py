"""Measured DACTE blocks over BrazilFiscalReport's XML reader (version 1.3.1).

MOC CT-e 4.00 Anexo II: same columns on continuation sheets, no ellipses,
Code128-C with >=10 module quiet zones and 15 mm bars, explicit environment.
This adapter covers normal road CT-e in portrait. Other profiles are rejected
explicitly rather than silently routed through the known lossy layout.
"""
from io import BytesIO
from math import ceil
import re
import xml.etree.ElementTree as ET

import qrcode
from barcode.charsets import code128
from brazilfiscalreport.dacte import Dacte
from brazilfiscalreport.dacte.dacte import extract_text
from brazilfiscalreport.dacte.dacte_conf import NS, TP_ICMS, TP_CODIGO_MEDIDA_REDUZIDO
from brazilfiscalreport.utils import format_cpf_cnpj, format_cep, format_phone, format_number, get_date_utc


class PreviewDacte(Dacte):
    def __init__(self, xml, config=None):
        root = ET.fromstring(xml)
        ide = root.find('.//' + NS + 'ide')
        if any(extract_text(ide, tag) != value for tag, value in
               [('tpImp', '1'), ('modal', '01'), ('tpCTe', '0'), ('tpEmis', '1'), ('tpServ', '0')]):
            from .core import DomainError
            raise DomainError('Prévia DACTE com composição revisada disponível para CT-e normal rodoviário, retrato e emissão normal. Este perfil exige validação específica; XML preservado.', 422, 'renderer_not_validated')
        special = {'peri', 'veicNovos', 'infGlobalizado', 'infCTeMultimodal', 'infServVinc'}
        if any(node.tag.removeprefix(NS) in special for node in root.iter()):
            from .core import DomainError
            raise DomainError('CT-e com grupo especial ainda sem composição de prévia validada; XML original preservado.',422,'renderer_not_validated')
        self.layout_boxes = []
        super().__init__(xml, config)

    def _lines(self, text, width, size=7, bold=False):
        self.set_font(self.default_font, 'B' if bold else '', size)
        return self.multi_cell(w=width, h=3, text=str(text or ''), dry_run=True, output='LINES') or ['']

    def _text(self, x, y, width, lines, size=7, bold=False, align='L', leading=3):
        self.set_font(self.default_font, 'B' if bold else '', size)
        self.set_xy(x, y)
        self.multi_cell(w=width, h=leading, text='\n'.join(lines), align=align)

    def _box(self, x, y, w, h, text, *, size=7, bold=False, align='L'):
        lines = self._lines(text, w-2, size, bold)
        if len(lines)*3+2 > h+0.01:
            raise ValueError('DACTE header field exceeds measured box')
        self.rect(x, y, w, h)
        self._text(x+1, y+1, w-2, lines, size, bold, align)
        self.layout_boxes.append((self.page_no(), x, y, w, h))

    def _new_sheet(self):
        self.add_page(orientation='P')
        self._draw_receipt()
        self._draw_header()

    def _ensure(self, height):
        if self.get_y()+height > self.h-28:
            self._new_sheet()

    def _section(self, title):
        # Defer until the first row is measured: never orphan a section title.
        self._pending_section = title

    def _heading(self, title):
        self._ensure(10)
        y = self.get_y()
        self._box(self.l_margin, y, self.epw, 5, title, bold=True, align='C')
        self.set_xy(self.l_margin, y+5)

    def _row(self, values, widths=None, *, size=7, bold=False, continuation=None):
        """Wrap each column, then split oversized rows without dropping a line."""
        widths = widths or [self.epw/len(values)]*len(values)
        lines = [self._lines(value, width-2, size, bold) for value,width in zip(values,widths)]
        whole_height = max(map(len, lines))*3+2
        pending = getattr(self, '_pending_section', None)
        if pending:
            self._ensure(min(whole_height, self.h-28-self.body_top-5)+5)
            self._heading(pending)
            self._active_section = pending
            self._pending_section = None
        continuation = continuation or getattr(self, '_active_section', None)
        if self.get_y()+whole_height > self.h-28 and whole_height <= self.h-28-self.body_top:
            self._new_sheet()
            if continuation:
                self._heading(continuation+' - CONTINUAÇÃO')
        while any(lines):
            available = int((self.h-28-self.get_y()-2)/3)
            if available < 1:
                self._new_sheet()
                if continuation:
                    self._heading(continuation + ' - CONTINUAÇÃO')
                continue
            count = min(max(map(len, lines)), available)
            h = count*3+2
            x, y = self.l_margin, self.get_y()
            for index,width in enumerate(widths):
                part, lines[index] = lines[index][:count], lines[index][count:]
                self.rect(x, y, width, h)
                if part:
                    self._text(x+1, y+1, width-2, part, size, bold)
                self.layout_boxes.append((self.page_no(), x, y, width, h))
                x += width
            self.set_xy(self.l_margin, y+h)
            if any(lines):
                self._new_sheet()
                if continuation:
                    self._heading(continuation+' - CONTINUAÇÃO')

    @staticmethod
    def _party(node):
        get = lambda tag: extract_text(node, tag)
        identity = get('CNPJ') or get('CPF')
        address = ', '.join(filter(None, (get('xLgr'), get('nro'), get('xCpl'), get('xBairro'))))
        return '\n'.join(filter(None, (
            get('xNome'),
            'ENDEREÇO: '+address if address else '',
            'MUNICÍPIO: '+get('xMun')+' - '+get('UF')+'  CEP: '+format_cep(get('CEP')) if get('xMun') else '',
            'CNPJ/CPF: '+format_cpf_cnpj(identity)+'  IE: '+get('IE') if identity else '',
            '  '.join(filter(None, ('PAÍS: '+get('xPais') if get('xPais') else '', 'FONE: '+format_phone(get('fone')) if get('fone') else ''))),
            'SUFRAMA: '+get('ISUF') if get('ISUF') else '',
        )))

    def _barcode(self, x, y, module):
        if not re.fullmatch(r'\d{44}', self.key_cte):
            raise ValueError('Code128-C requires exactly 44 digits')
        symbols = [105]+[int(self.key_cte[i:i+2]) for i in range(0,44,2)]
        checksum = (symbols[0]+sum(i*value for i,value in enumerate(symbols[1:],1))) % 103
        bits = ''.join(code128.CODES[value] for value in symbols+[checksum])+code128.STOP+'11'
        # Contiguous runs, not independently antialiased rectangles per module.
        self.set_fill_color(255)
        self.rect(x, y, 297*module, 15, 'F')
        self.set_fill_color(0)
        for run in re.finditer('1+', bits):
            self.rect(x+(10+run.start())*module, y, len(run[0])*module, 15, 'F')

    def footer(self):
        if not hasattr(self, 'key_cte'):
            return
        # Additional code of the SAME XML key in the footer is allowed by
        # MOC 2.21.3. Different valid module pitch avoids identical raster aliasing
        # on both symbols. Both retain 10X quiet zones and 15mm bar height.
        self._barcode(self.l_margin+61, self.h-24, 25.4/96)
        self._text(self.l_margin+60, self.h-9, 94,
                   [' '.join(self.key_cte[i:i+4] for i in range(0,44,4))], 6, align='C')

    def _draw_header(self):
        x, y = self.l_margin, 27
        left, middle, right = 60, 94, self.epw-154
        issuer = self._party(self.emit)
        issuer_h = max(28, len(self._lines(issuer,left-2))*3+2)
        metadata = [('TIPO DO CT-E',self.tp_cte), ('TIPO DO SERVIÇO',self.tp_serv),
                    ('TOMADOR DO SERVIÇO',self.toma), ('CFOP - NATUREZA DA PRESTAÇÃO',self.cfop+' - '+self.nat_op)]
        meta_lines = [(title+'\n'+value) for title,value in metadata]
        heights = [len(self._lines(value,left-2))*3+2 for value in meta_lines]
        height = max(76, issuer_h+sum(heights))
        if y+height > 165:
            raise ValueError('DACTE issuer exceeds safe header capacity')
        self._box(x,y,left,issuer_h,issuer)
        cursor = y+issuer_h
        for value,h in zip(meta_lines,heights):
            self._box(x,cursor,left,h,value)
            cursor += h
        if cursor < y+height:
            self.rect(x,cursor,left,y+height-cursor)
        mx = x+left
        self.rect(mx,y,middle,12)
        self._text(mx+1,y+1,middle-2,['DACTE'],12,True,'C',5)
        self._text(mx+1,y+6,middle-2,['DOCUMENTO AUXILIAR DO CONHECIMENTO','DE TRANSPORTE ELETRÔNICO'],6.5,False,'C',2.5)
        date,time = get_date_utc(extract_text(self.ide,'dhEmi'))
        widths = [14,10,19,35,16]
        values = ['MODELO\n'+self.mod,'SÉRIE\n'+self.serie_cte,'NÚMERO\n'+self.nr_dacte,
                  'DATA E HORA DE EMISSÃO\n'+date+' '+time, f'FOLHA\n{self.page_no()}/{{nb}}']
        cx = mx
        for value,width in zip(values,widths):
            self._box(cx,y+12,width,12,value,size=6,align='C')
            cx += width
        self.rect(mx,y+24,middle,18)
        self._barcode(mx+1,y+25.5,25.4/90)
        self._box(mx,y+42,middle,9,'CHAVE DE ACESSO\n'+' '.join(self.key_cte[i:i+4] for i in range(0,44,4)),align='C')
        self._box(mx,y+51,middle,6,'CONSULTA EM http://www.cte.fazenda.gov.br',size=7,align='C')
        self._box(mx,y+57,middle,9,'PROTOCOLO DE AUTORIZAÇÃO DE USO\n'+self.prot_uso,align='C')
        environment = 'EMITIDO EM AMBIENTE DE HOMOLOGAÇÃO - SEM VALOR FISCAL' if extract_text(self.ide,'tpAmb')=='2' else ('SEM VALOR FISCAL - PROTOCOLO AUSENTE' if self.prot_cte is None else '')
        if self.watermark_cancelled:
            environment = 'CANCELADA\n'+environment
        self._box(mx,y+66,middle,height-66,environment,bold=True,align='C')
        rx = mx+middle
        self._box(rx,y,right,12,'MODAL\nRODOVIÁRIO',bold=True,align='C')
        self.rect(rx,y+12,right,height-12)
        payload = extract_text(self.inf_cte_supl,'qrCodCTe')
        if payload:
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L,box_size=12,border=0)
            qr.add_data(payload);qr.make(fit=True)
            qr.border = max(4,ceil(qr.modules_count/8))
            buffer = BytesIO();qr.make_image(fill_color='black',back_color='white').save(buffer,format='PNG')
            self.image(BytesIO(buffer.getvalue()),x=rx+(right-38)/2,y=y+17,w=38,h=38)
        self.body_top = y+height
        self.set_xy(x,self.body_top)

    def _draw_recipient_sender(self, config):
        self._row(['INÍCIO DA PRESTAÇÃO\n'+extract_text(self.ide,'xMunIni')+' - '+extract_text(self.ide,'UFIni'),
                   'TÉRMINO DA PRESTAÇÃO\n'+extract_text(self.ide,'xMunFim')+' - '+extract_text(self.ide,'UFFim')])
        self._row(['REMETENTE\n'+self._party(self.rem),'DESTINATÁRIO\n'+self._party(self.dest)],continuation='REMETENTE / DESTINATÁRIO')
        if self.exped is not None or self.receb is not None:
            self._row(['EXPEDIDOR\n'+self._party(self.exped),'RECEBEDOR\n'+self._party(self.receb)],continuation='EXPEDIDOR / RECEBEDOR')

    def _draw_service_recipient(self, config):
        node = {'REMETENTE':self.rem,'DESTINATÁRIO':self.dest,'EXPEDIDOR':self.exped,'RECEBEDOR':self.receb,'OUTRO':self.outros}[self.toma]
        self._row(['TOMADOR DO SERVIÇO\n'+self._party(node)],continuation='TOMADOR DO SERVIÇO')
        self._row(['PRODUTO PREDOMINANTE\n'+extract_text(self.inf_carga,'proPred'),
                   'VALOR TOTAL DA CARGA\n'+format_number(extract_text(self.inf_carga,'vCarga'),precision=2)],widths=[140,self.epw-140])
        self._section('INFORMAÇÕES DA CARGA')
        items = [(unit,kind,value) for unit,kind,value in self.inf_carga_list if unit or kind or value]
        cubage = '\n'.join(value for unit,kind,value in items if unit=='00')
        volumes = '\n'.join(value for unit,kind,value in items if unit=='03' and kind.strip().upper()!='PARES')
        for index in range(0,max(1,len(items)),3):
            values = ['TIPO MEDIDA: '+kind+'\nQTD/UN.: '+value+' '+TP_CODIGO_MEDIDA_REDUZIDO.get(unit,unit) for unit,kind,value in items[index:index+3]]
            self._row(values+['']*(3-len(values))+['CUBAGEM (M3)\n'+cubage if index==0 else '', 'QTD DE VOLUMES\n'+volumes if index==0 else ''],
                      widths=[50,50,50,25,self.epw-175], continuation='INFORMAÇÕES DA CARGA')

    def _draw_service_fee_value(self):
        self._section('COMPONENTES DO VALOR DA PRESTAÇÃO DO SERVIÇO')
        for index in range(0,max(6,len(self.comp_list)),3):
            values = [name+'\nVALOR: '+format_number(value,precision=2) for name,value in self.comp_list[index:index+3]]
            total = ('VALOR TOTAL DO SERVIÇO\n'+format_number(extract_text(self.v_prest,'vTPrest'),precision=2) if index==0 else
                     'VALOR TOTAL A RECEBER\n'+format_number(extract_text(self.v_prest,'vRec'),precision=2) if index==3 else '')
            self._row(values+['']*(3-len(values))+[total],continuation='COMPONENTES DO VALOR DA PRESTAÇÃO DO SERVIÇO')
        self._section('INFORMAÇÕES RELATIVAS AO IMPOSTO')
        cst = extract_text(self.icms,'CST')
        values = [cst+' - '+TP_ICMS.get(cst,''),extract_text(self.icms,'vBC'),extract_text(self.icms,'pICMS'),
                  extract_text(self.icms,'vICMS'),extract_text(self.icms,'pRedBC'),extract_text(self.icms,'vICMSST') or extract_text(self.icms,'vICMSSTRet')]
        labels = ['SITUAÇÃO TRIBUTÁRIA','BASE DE CÁLCULO','ALÍQ. ICMS','VALOR ICMS','RED. BC ICMS (%)','ICMS ST']
        self._row([label+'\n'+(format_number(value,precision=2) if i and value else value) for i,(label,value) in enumerate(zip(labels,values))],size=6)
        if self.imp_ibscbs is not None:
            self._section('IBS / CBS - DADOS DO XML')
            self._row(['IBS UF (% / R$)\n'+self.p_ibs_uf+' / '+self.v_ibs_uf,
                       'IBS MUNICIPAL (% / R$)\n'+self.p_ibs_mun+' / '+self.v_ibs_mun,
                       'CBS (% / R$)\n'+self.p_cbs+' / '+self.v_cbs])

    def _draw_documents_obs(self):
        self._section('DOCUMENTOS ORIGINÁRIOS')
        documents = []
        for node in self.inf_doc if self.inf_doc is not None else []:
            kind = node.tag.removeprefix(NS)
            if kind == 'infNFe':
                key = extract_text(node,'chave')
                documents.append('NF-e / CNPJ-CHAVE\n'+key+'\nSÉRIE/Nº: '+key[22:25]+'/'+key[25:34])
            elif kind in ('infNF','infOutros'):
                labels = {'mod':'MODELO','serie':'SÉRIE','nDoc':'NÚMERO','dEmi':'EMISSÃO',
                          'tpDoc':'TIPO','descOutros':'DESCRIÇÃO','vDocFisc':'VALOR','CNPJ':'CNPJ','CPF':'CPF'}
                documents.append(('NF' if kind=='infNF' else 'OUTROS')+'\n'+'\n'.join(
                    labels.get(child.tag.removeprefix(NS),child.tag.removeprefix(NS))+': '+child.text.strip()
                    for child in node.iter() if not len(child) and child.text and child.text.strip()))
            else:
                from .core import DomainError
                raise DomainError('Referência documental CT-e sem composição validada; XML preservado.',422,'renderer_not_validated')
        for index in range(0,len(documents),2):
            values = documents[index:index+2]
            self._row(values+['']*(2-len(values)),continuation='DOCUMENTOS ORIGINÁRIOS')
        self._section('OBSERVAÇÕES')
        observations = []
        if self.compl is not None:
            for node in self.compl.iter():
                if node.tag in (NS+'xObs', NS+'xTexto') and node.text:
                    observations.append(node.text.strip())
        for observation in observations or ['']:
            self._row([observation],continuation='OBSERVAÇÕES')

    def _draw_specific_data(self, config):
        self._section('DADOS ESPECÍFICOS DO MODAL RODOVIÁRIO - CARGA FRACIONADA')
        self._row(['RNTRC DA EMPRESA\n'+extract_text(self.inf_modal,'RNTRC'),
                   'CIOT\n'+extract_text(self.inf_modal,'CIOT'),
                   'DATA PREVISTA DE ENTREGA\n'+extract_text(self.compl,'dProg'),
                   'ESTE CONHECIMENTO DE TRANSPORTE ATENDE À LEGISLAÇÃO DE TRANSPORTE RODOVIÁRIO EM VIGOR'])
        self._section('USO EXCLUSIVO DO EMISSOR DO CT-E')
        self._row([''])
        self._section('RESERVADO AO FISCO')
        self._row([''])

    def _draw_void_watermark(self):
        # The optional diagonal mark obscured fiscal data. Mandatory environment
        # identification is centered in every header, never removed or covered.
        pass

    def _add_new_page(self, config):
        # Pagination is performed by measured rows, not upstream character counts.
        pass
