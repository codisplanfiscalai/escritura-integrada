// O aplicativo Qt usa o leitor nativo já integrado ao comando de abrir PDF.
// Evita frames vazios ou downloads inesperados quando não há leitor embutido.
export function supportsEmbeddedPdf(browser = globalThis.navigator) {
  return browser?.pdfViewerEnabled === true && !/QtWebEngine\//i.test(browser?.userAgent || '');
}
