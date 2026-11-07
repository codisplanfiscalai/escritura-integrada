import test from 'node:test';
import assert from 'node:assert/strict';
import {supportsEmbeddedPdf} from '../src/lib/pdf-preview.js';

test('navegador com leitor permite prévia embutida', () => {
  assert.equal(supportsEmbeddedPdf({pdfViewerEnabled:true,userAgent:'Chrome/151.0'}),true);
});
test('navegador sem leitor mantém abertura externa', () => {
  assert.equal(supportsEmbeddedPdf({pdfViewerEnabled:false,userAgent:'Chrome/151.0'}),false);
  assert.equal(supportsEmbeddedPdf({userAgent:'Chrome/151.0'}),false);
});
test('aplicativo Qt preserva visualizador nativo mesmo com suporte anunciado', () => {
  assert.equal(supportsEmbeddedPdf({pdfViewerEnabled:true,userAgent:'QtWebEngine/6.11.1 Chrome/151.0'}),false);
});
