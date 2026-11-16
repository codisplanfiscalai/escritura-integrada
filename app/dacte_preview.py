"""Local, version-bound DACTE QR repair; upstream text-layout limits still apply.

MOC CT-e 4.00 Anexo II, 2.18/2.20/2.21.1: preserve the XML payload,
quiet zone, homologation identification, and readability under watermarks.
No changes to the XML or the installed third-party package.
"""
from io import BytesIO
from math import ceil

import qrcode
from brazilfiscalreport.dacte import Dacte
from brazilfiscalreport.dacte.dacte import extract_text


class PreviewDacte(Dacte):
    def _draw_header(self):
        super()._draw_header()
        self._protected_qr()

    def _draw_void_watermark(self):
        # Keep the original environment/cancellation marking on the page.
        super()._draw_void_watermark()
        # A watermark may not interfere with the code or its quiet zone.
        self._protected_qr()

    def _protected_qr(self):
        payload = extract_text(self.inf_cte_supl, 'qrCodCTe')
        if not payload:
            return
        # QR location and 38 mm size match BrazilFiscalReport 1.3.1 header.
        # At >25 mm, MOC requires a quiet margin of 10% of total dimension.
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L,
                           box_size=12, border=0)
        qr.add_data(payload)
        qr.make(fit=True)
        qr.border = max(4, ceil(qr.modules_count / 8))
        output = BytesIO()
        qr.make_image(fill_color='black', back_color='white').save(output, format='PNG')
        x = self.l_margin + self.epw / 2 - 33 + 89
        y = self.t_margin + 33
        previous_x, previous_y = self.get_x(), self.get_y()
        with self.local_context():
            self.image(BytesIO(output.getvalue()), x=x, y=y, w=38, h=38)
            if extract_text(self.ide, 'tpAmb') == '2':
                # Explicit mandatory identification in the variable header area.
                # White background isolates it from the optional diagonal mark.
                self.set_fill_color(255, 255, 255)
                self.rect(x-4, y+39, 46, 10, style='F')
                self.set_text_color(0, 0, 0)
                self.set_font(self.default_font, 'B', 6)
                self.set_xy(x-4, y+39)
                self.multi_cell(w=46, h=2.7, align='C', text=(
                    'EMITIDO EM AMBIENTE DE\nHOMOLOGAÇÃO - SEM VALOR FISCAL'))
        self.set_xy(previous_x, previous_y)
