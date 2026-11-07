"""Visualização de PDFs do Auditor com a sessão local e o Qt já distribuído."""
from urllib.parse import urlsplit, parse_qs
import re


def preview_url_allowed(value,base):
    try:
        url,origin=urlsplit(value),urlsplit(base)
        if (url.scheme,url.hostname,url.port)!=('http','127.0.0.1',origin.port) or url.username or url.password or url.fragment:return False
        if origin.scheme!='http' or origin.hostname!='127.0.0.1':return False
        match=re.fullmatch(r'/api/companies/[0-9]+/auditor/jobs/[0-9]+/(report|files)',url.path)
        query=parse_qs(url.query)
        if not match:return False
        if match[1]=='report':return query.get('format')==['pdf'] and query.get('purpose')==['print']
        return query.get('inline')==['1'] and len(query.get('file_id',[]))==1 and query['file_id'][0].isdigit()
    except ValueError:return False


def show_pdf(parent,path,ready=None):
    from pathlib import Path
    import shutil
    from PySide6.QtCore import QSize,Qt,QTimer
    from PySide6.QtGui import QPainter,QPageLayout
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    from PySide6.QtPrintSupport import QPrinter,QPrintDialog
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QFileDialog,QMessageBox
    dialog=QDialog(parent);dialog.setWindowTitle('Auditor Fiscal · PDF');dialog.resize(1100,800)
    layout=QVBoxLayout(dialog);bar=QHBoxLayout();label=QLabel('Abrindo PDF…');bar.addWidget(label);bar.addStretch()
    save=QPushButton('Salvar PDF…');print_button=QPushButton('Imprimir…');close=QPushButton('Fechar · Esc')
    for b in (save,print_button,close):bar.addWidget(b)
    layout.addLayout(bar);view=QPdfView(dialog);document=QPdfDocument(dialog)
    view.setPageMode(QPdfView.PageMode.MultiPage);view.setZoomMode(QPdfView.ZoomMode.FitToWidth);view.setDocument(document);layout.addWidget(view)
    close.clicked.connect(dialog.close)
    def save_as():
        target,_=QFileDialog.getSaveFileName(dialog,'Salvar PDF','auditoria.pdf','PDF (*.pdf)')
        if target:
            try:shutil.copyfile(path,target)
            except OSError:QMessageBox.warning(dialog,'Salvar PDF','Não foi possível gravar o arquivo no destino selecionado.')
    save.clicked.connect(save_as)
    def print_pdf():
        printer=QPrinter(QPrinter.PrinterMode.HighResolution);chooser=QPrintDialog(printer,dialog)
        if chooser.exec()!=QDialog.Accepted:return
        painter=QPainter()
        try:
            for n in range(document.pageCount()):
                size=document.pagePointSize(n)
                printer.setPageOrientation(QPageLayout.Landscape if size.width()>size.height() else QPageLayout.Portrait)
                if n==0:
                    if not painter.begin(printer):raise RuntimeError()
                elif not printer.newPage():raise RuntimeError()
                rect=printer.pageRect(QPrinter.Unit.DevicePixel).toRect()
                scale=min(rect.width()/size.width(),rect.height()/size.height())
                image=document.render(n,QSize(int(size.width()*scale),int(size.height()*scale)))
                if image.isNull():raise RuntimeError()
                painter.drawImage(rect.x(),rect.y(),image)
        except Exception:QMessageBox.warning(dialog,'Imprimir PDF','A impressão não foi concluída. Confira a impressora e tente novamente.')
        finally:
            if painter.isActive():painter.end()
    print_button.clicked.connect(print_pdf)
    def status_changed(status):
        if status==QPdfDocument.Status.Ready:
            label.setText(f'{document.pageCount()} páginas · PDF preservado')
            save.setEnabled(True);print_button.setEnabled(True)
            if ready:QTimer.singleShot(500,dialog,lambda:ready(document.pageCount(),dialog))
        elif status==QPdfDocument.Status.Error:
            label.setText('PDF inválido ou protegido; original preservado.')
    save.setEnabled(False);print_button.setEnabled(False);document.statusChanged.connect(status_changed)
    dialog.finished.connect(lambda _:document.close())
    dialog.show();document.load(str(path))
    # Mantém objetos Python durante a vida da janela nativa.
    dialog._pdf_document=document;dialog._pdf_view=view
    return dialog
